// 파일 열기·편집 모드·저장·외부 변경 감지 — 원본 open_file / load_file / 편집 모드 / save_edit / 파일 변경 (v2.2.7~v2.3.3)
// PG ADD(여러 파일 이어붙이기)는 Android 버전에서 제외했으므로 파일은 항상 하나다.
import { PyError } from '../core/py';
import {
  createEditPasswordEntry, EDIT_PASSWORD_DEFAULT, verifyEditPassword,
} from '../core/password';
import {
  decodeProgramBytes, encodeProgramText, type ProgramEncoding, programTextDigest,
} from '../core/programText';
import {
  type FileInfo, type OpenedFile, openFile, readFile, saveAs, saveBackup, statFile, takeIncoming, writeFile,
  canWriteInPlace,
} from '../platform/files';
import { getPref, setPref } from '../platform/prefs';
import { alertDialog, choiceDialog, confirmDialog, promptDialog, toast } from '../ui/dialog';
import type { Editor } from '../ui/editor';

export interface DocumentDeps {
  editor: Editor;
  /** 프로그램 내용이 통째로 바뀐 뒤(열기·예제·지우기·새로고침) 표를 다시 만든다 */
  onTextReplaced: () => void;
  /** 편집 중 내용이 바뀌어 표를 다시 만든다(디바운스 후) */
  onEditRefresh: () => void;
  /** 표에서 직접 고친 내용이 있는가 (편집 모드로 들어가면 사라진다) */
  isTableEdited: () => boolean;
  /** 편집 모드 표시를 바꿀 때 */
  onEditModeChange: (editing: boolean) => void;
  /** 열린 파일 이름이 바뀔 때 (제목 표시 등) */
  onFileChange: (name: string | null) => void;
}

interface Source {
  info: FileInfo;
  encoding: ProgramEncoding;
  newline: '\n' | '\r\n';
  lossy: boolean;
  /** 읽었을 때(또는 마지막으로 저장했을 때) 내용의 SHA-1 */
  digest: string;
}

export interface DocumentController {
  editing(): boolean;
  hasUnsavedChanges(): boolean;
  /** 저장하지 않은 편집이 있으면 저장/버림/취소를 묻는다. 계속해도 되면 true */
  confirmDiscardEdits(): Promise<boolean>;
  open(): Promise<void>;
  openIncoming(): Promise<void>;
  /** 파일이 아닌 내용(예제·지우기)으로 바꾼다 */
  setPlainText(text: string): Promise<void>;
  toggleEdit(): Promise<void>;
  save(): Promise<boolean>;
  changePassword(): Promise<void>;
  checkExternalChange(): Promise<void>;
  fileName(): string | null;
}

const EDIT_REFRESH_MS = 400;

export function createDocumentController(deps: DocumentDeps): DocumentController {
  const { editor } = deps;
  let source: Source | null = null;
  let editMode = false;
  let savedText = '';
  let ignoredDigest: string | null = null;
  let missingNotified = false;
  let promptOpen = false;
  let refreshTimer = 0;

  const passwordEntry = (): unknown => {
    try {
      const raw = getPref('edit_password');
      return raw ? (JSON.parse(raw) as unknown) : undefined;
    } catch {
      return undefined; // 깨졌으면 기본 비밀번호로 돌아간다(원본과 같다)
    }
  };

  const hasUnsaved = (): boolean => editMode && editor.getText() !== savedText;

  const setEditMode = (on: boolean): void => {
    editMode = on;
    window.clearTimeout(refreshTimer);
    editor.setReadOnly(!on);
    deps.onEditModeChange(on);
    if (on) editor.focus();
  };

  const askSave = (): Promise<string | null> =>
    choiceDialog('편집 내용', '저장하지 않은 변경이 있습니다. 저장할까요?', [
      { label: '취소', value: 'cancel' },
      { label: '저장 안 함', value: 'discard' },
      { label: '저장', value: 'save', primary: true },
    ]);

  const restoreSaved = (): void => {
    editor.setText(savedText);
    deps.onTextReplaced();
  };

  const confirmDiscardEdits = async (): Promise<boolean> => {
    if (!hasUnsaved()) return true;
    const choice = await askSave();
    if (choice === 'save') return save();
    if (choice === 'discard') {
      restoreSaved();
      return true;
    }
    return false;
  };

  /** 읽은 파일을 화면에 올린다. */
  const apply = async (file: OpenedFile, keepPosition = false): Promise<void> => {
    const decoded = decodeProgramBytes(file.bytes);
    const digest = await programTextDigest(decoded.text);
    const scroll = editor.view.scrollDOM.scrollTop;
    const caret = editor.selectionFrom();
    const wasLathe = false;
    void wasLathe;
    source = { info: file, encoding: decoded.encoding, newline: decoded.newline, lossy: decoded.lossy, digest };
    ignoredDigest = null;
    missingNotified = false;
    editor.setText(decoded.text);
    savedText = decoded.text;
    if (keepPosition) {
      editor.select(Math.min(caret, decoded.text.length), Math.min(caret, decoded.text.length));
      editor.view.scrollDOM.scrollTop = scroll;
    }
    deps.onTextReplaced();
    deps.onFileChange(file.name);
    if (decoded.lossy) {
      toast('읽을 수 없는 글자가 있어 깨진 글자(�)로 표시했습니다. 저장은 다른 이름으로 하세요.', 5000);
    }
  };

  const open = async (): Promise<void> => {
    if (!(await confirmDiscardEdits())) return;
    let file: OpenedFile | null;
    try {
      file = await openFile();
    } catch (error) {
      await alertDialog('열기 실패', String((error as Error).message ?? error));
      return;
    }
    if (file) await apply(file);
  };

  const openIncoming = async (): Promise<void> => {
    let file: OpenedFile | null;
    try {
      file = await takeIncoming();
    } catch (error) {
      await alertDialog('열기 실패', String((error as Error).message ?? error));
      return;
    }
    if (!file) return;
    if (!(await confirmDiscardEdits())) return;
    await apply(file);
  };

  const setPlainText = async (text: string): Promise<void> => {
    if (!(await confirmDiscardEdits())) return;
    source = null;
    ignoredDigest = null;
    editor.setText(text);
    savedText = text;
    deps.onTextReplaced();
    deps.onFileChange(null);
  };

  // ---------------------------------------------------------------- 편집 모드
  const toggleEdit = async (): Promise<void> => {
    if (!editMode) {
      const pw = await promptDialog('편집 모드', '비밀번호를 입력하세요.', { password: true });
      if (pw === null) return;
      if (!(await verifyEditPassword(pw, passwordEntry()))) {
        await alertDialog('편집 모드', '비밀번호가 올바르지 않습니다.');
        return;
      }
      if (deps.isTableEdited() && !(await confirmDialog(
        '편집 모드', '프로그램을 고치면 툴리스트가 다시 만들어져 표에서 직접 수정한 내용이 사라집니다.\n계속할까요?', '계속'))) return;
      savedText = editor.getText();
      setEditMode(true);
      return;
    }
    if (hasUnsaved()) {
      const choice = await askSave();
      if (choice === 'cancel' || choice === null) return;
      if (choice === 'save' && !(await save())) return;
      if (choice === 'discard') restoreSaved();
    }
    setEditMode(false);
  };

  editor.onUserEdit = () => {
    if (!editMode) return;
    window.clearTimeout(refreshTimer);
    refreshTimer = window.setTimeout(() => deps.onEditRefresh(), EDIT_REFRESH_MS);
  };

  // ---------------------------------------------------------------- 저장
  const save = async (): Promise<boolean> => {
    const text = editor.getText();
    let target = source?.info ?? null;
    if (source?.lossy && target) {
      await alertDialog('저장', '원본에 읽을 수 없는 글자가 있어 덮어쓰면 그 글자가 손상됩니다.\n다른 이름으로 저장하세요.');
      target = null;
    }
    const encoding: ProgramEncoding | string = source?.encoding ?? 'utf-8';
    const newline = source?.newline ?? '\n';
    let bytes: Uint8Array;
    try {
      bytes = encodeProgramText(text, encoding, newline); // 쓰기 전에 인코딩부터 확인한다
    } catch (error) {
      if (error instanceof PyError && error.pyType === 'UnicodeEncodeError') {
        await alertDialog('저장 실패', `현재 인코딩(${encoding})으로 표현할 수 없는 글자가 있어 저장하지 않았습니다.`);
        return false;
      }
      throw error;
    }
    try {
      let saved: FileInfo | null;
      if (target?.uri && target.writable) {
        try {
          const old = await readFile(target.uri);
          await saveBackup(target.name, old.bytes); // 원래 내용을 .bak 로 남긴다
        } catch {
          /* 원본을 못 읽어도 저장은 계속한다 */
        }
        saved = await writeFile(target.uri, bytes);
      } else {
        if (target && !canWriteInPlace()) toast('브라우저에서는 내려받기로 저장합니다');
        saved = await saveAs(target?.name ?? 'program.nc', bytes);
        if (!saved) return false;
      }
      const digest = await programTextDigest(text);
      source = {
        info: { ...saved, name: saved.name || target?.name || 'program.nc', uri: saved.uri ?? target?.uri ?? null },
        encoding: (source?.encoding ?? 'utf-8') as ProgramEncoding, newline, lossy: false, digest,
      };
      ignoredDigest = null;
      savedText = text;
      deps.onFileChange(source.info.name);
      toast(`저장했습니다: ${source.info.name}`);
      return true;
    } catch (error) {
      await alertDialog('저장 실패', String((error as Error).message ?? error));
      return false;
    }
  };

  // ---------------------------------------------------------------- 비밀번호 변경
  const changePassword = async (): Promise<void> => {
    const current = await promptDialog('비밀번호 변경', '현재 비밀번호', { password: true });
    if (current === null) return;
    if (!(await verifyEditPassword(current, passwordEntry()))) {
      await alertDialog('비밀번호 변경', '현재 비밀번호가 올바르지 않습니다.');
      return;
    }
    const next = await promptDialog('비밀번호 변경', '새 비밀번호 (4자 이상)', { password: true });
    if (next === null) return;
    if (next.length < 4) {
      await alertDialog('비밀번호 변경', '비밀번호는 4자 이상이어야 합니다.');
      return;
    }
    const again = await promptDialog('비밀번호 변경', '새 비밀번호 확인', { password: true });
    if (again === null) return;
    if (again !== next) {
      await alertDialog('비밀번호 변경', '새 비밀번호가 서로 다릅니다.');
      return;
    }
    setPref('edit_password', JSON.stringify(await createEditPasswordEntry(next)));
    await alertDialog('비밀번호 변경', '비밀번호를 변경했습니다.');
  };

  // ---------------------------------------------------------------- 외부 변경 감지 (앱을 다시 켤 때)
  const checkExternalChange = async (): Promise<void> => {
    if (!source?.info.uri || promptOpen) return;
    const current = source;
    let stat: FileInfo | null;
    try {
      stat = await statFile(current.info.uri!);
    } catch {
      return;
    }
    if (!stat) {
      if (!missingNotified) {
        missingNotified = true;
        toast(`불러온 파일이 지워졌거나 이름이 바뀌었습니다: ${current.info.name}`, 5000);
      }
      return;
    }
    missingNotified = false;
    if (stat.size === current.info.size && stat.modified === current.info.modified) return;
    let fresh: OpenedFile;
    try {
      fresh = await readFile(current.info.uri!);
    } catch {
      return;
    }
    const digest = await programTextDigest(decodeProgramBytes(fresh.bytes).text);
    if (digest === current.digest || digest === ignoredDigest) {
      current.info = { ...current.info, size: fresh.size, modified: fresh.modified };
      return;
    }
    promptOpen = true;
    try {
      const modified = hasUnsaved();
      const message = `"${current.info.name}" 파일이 바뀌었습니다.\n다시 불러올까요?` +
        (modified ? '\n\n편집 중 저장하지 않은 수정 내용은 사라집니다.' : '');
      const choice = await choiceDialog('파일 변경', message, [
        { label: '무시', value: 'ignore' },
        { label: '새로고침', value: 'reload', primary: true },
      ]);
      if (choice === 'reload') {
        await apply(fresh, true);
        toast(`다시 불러왔습니다: ${fresh.name}`);
      } else {
        ignoredDigest = digest;
        current.info = { ...current.info, size: fresh.size, modified: fresh.modified };
      }
    } finally {
      promptOpen = false;
    }
  };

  void EDIT_PASSWORD_DEFAULT;
  return {
    editing: () => editMode,
    hasUnsavedChanges: hasUnsaved,
    confirmDiscardEdits,
    open,
    openIncoming,
    setPlainText,
    toggleEdit,
    save,
    changePassword,
    checkExternalChange,
    fileName: () => source?.info.name ?? null,
  };
}
