// 공용 부품: 대화상자, 토스트, 길게 누르면 설명(툴팁 대체)
export function el<K extends keyof HTMLElementTagNameMap>(
  tag: K, attrs: Record<string, string> = {}, html = '',
): HTMLElementTagNameMap[K] {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) node.setAttribute(k, v);
  if (html) node.innerHTML = html;
  return node;
}

export interface DialogButton {
  label: string;
  primary?: boolean;
  /** false 를 돌려주면 닫지 않는다 */
  onClick?: () => boolean | void;
}

/** 모달 대화상자. body 는 문자열(글자 그대로) 또는 만들어 둔 요소. */
export function showDialog(title: string, body: string | HTMLElement, buttons?: DialogButton[]): HTMLDialogElement {
  const dlg = el('dialog');
  const head = el('div', { class: 'dlg-head' });
  head.textContent = title;
  const content = el('div', { class: 'dlg-body' });
  if (typeof body === 'string') content.textContent = body;
  else content.append(body);
  const foot = el('div', { class: 'dlg-foot' });
  for (const spec of buttons ?? [{ label: '닫기', primary: true }]) {
    const b = el('button', { type: 'button', class: spec.primary ? 'primary' : '' });
    b.textContent = spec.label;
    b.addEventListener('click', () => {
      if (spec.onClick?.() !== false) dlg.close();
    });
    foot.append(b);
  }
  dlg.append(head, content, foot);
  dlg.addEventListener('close', () => dlg.remove());
  document.body.append(dlg);
  dlg.showModal();
  // 열자마자 첫 입력칸에 포커스가 가 키보드가 뜨는 것을 막는다 — 칸을 직접 눌러야 키보드가 뜬다
  (document.activeElement as HTMLElement | null)?.blur();
  return dlg;
}

/** 예/아니오 확인. 결과는 Promise<boolean>. */
export function confirmDialog(title: string, message: string, yes = '확인', no = '취소'): Promise<boolean> {
  return new Promise((resolve) => {
    let answer = false;
    const dlg = showDialog(title, message, [
      { label: no },
      { label: yes, primary: true, onClick: () => { answer = true; } },
    ]);
    dlg.addEventListener('close', () => resolve(answer));
  });
}

let toastTimer = 0;
/** 아래쪽에 잠깐 뜨는 안내 */
export function toast(message: string, ms = 2200): void {
  let node = document.getElementById('toast');
  if (!node) {
    node = el('div', { id: 'toast', role: 'status' });
    document.body.append(node);
  }
  node.textContent = message;
  node.classList.add('show');
  window.clearTimeout(toastTimer);
  toastTimer = window.setTimeout(() => node!.classList.remove('show'), ms);
}

/** 길게 누르면 title 을 토스트로 보여 준다(터치에는 마우스 올리기가 없다). */
export function installLongPressHints(root: HTMLElement, delay = 550): void {
  let timer = 0;
  const cancel = () => window.clearTimeout(timer);
  root.addEventListener('pointerdown', (ev) => {
    const target = (ev.target as HTMLElement).closest<HTMLElement>('[title]');
    if (!target) return;
    cancel();
    timer = window.setTimeout(() => toast(target.title, 2600), delay);
  });
  for (const type of ['pointerup', 'pointercancel', 'pointermove', 'scroll']) root.addEventListener(type, cancel, true);
}

/** 글자 한 줄 입력(비밀번호면 가려서). 취소하면 null. */
export function promptDialog(title: string, label: string, opts: { password?: boolean; value?: string; ok?: string } = {}): Promise<string | null> {
  return new Promise((resolve) => {
    const wrap = el('div', { class: 'row-form single' });
    const lab = el('label');
    const name = el('span');
    name.textContent = label;
    const input = el('input', {
      type: opts.password ? 'password' : 'text', autocomplete: 'off', autocapitalize: 'off', spellcheck: 'false',
    });
    input.value = opts.value ?? '';
    lab.append(name, input);
    wrap.append(lab);
    let answer: string | null = null;
    const dlg = showDialog(title, wrap, [
      { label: '취소' },
      { label: opts.ok ?? '확인', primary: true, onClick: () => { answer = input.value; } },
    ]);
    input.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') {
        answer = input.value;
        dlg.close();
      }
    });
    dlg.addEventListener('close', () => resolve(answer));
    setTimeout(() => input.focus(), 50);
  });
}

/** 여러 선택지 중 하나. 닫기/바깥 취소는 null. */
export function choiceDialog(title: string, message: string, choices: { label: string; value: string; primary?: boolean }[]): Promise<string | null> {
  return new Promise((resolve) => {
    let answer: string | null = null;
    const dlg = showDialog(title, message, choices.map((c) => ({
      label: c.label, primary: c.primary, onClick: () => { answer = c.value; },
    })));
    dlg.addEventListener('close', () => resolve(answer));
  });
}

/** 확인만 있는 안내창 */
export function alertDialog(title: string, message: string): Promise<void> {
  return new Promise((resolve) => {
    const dlg = showDialog(title, message);
    dlg.addEventListener('close', () => resolve());
  });
}
