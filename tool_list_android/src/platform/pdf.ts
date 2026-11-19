// PDF 만들기 — pdfmake(브라우저판) + 번들한 Noto Sans KR 부분 글꼴. 문서 정의는 core/pdfLayout.ts.
import { buildPdfDefinition, FONT_REGULAR, type PdfRow } from '../core/pdfLayout';
import { defaultPdfFilename, type ProgramMetadata } from '../core/metadata';
import { toBase64 } from './files';

let pdfMakePromise: Promise<any> | null = null;

async function loadFont(name: string): Promise<string> {
  const res = await fetch(`${import.meta.env.BASE_URL}fonts/${name}`);
  if (!res.ok) throw new Error(`글꼴을 읽지 못했습니다: ${name}`);
  return toBase64(new Uint8Array(await res.arrayBuffer()));
}

function pdfMake(): Promise<any> {
  pdfMakePromise ??= (async () => {
    const mod: any = await import('pdfmake/build/pdfmake');
    const pm = mod.default ?? mod;
    const [regular, bold] = await Promise.all([
      loadFont('NotoSansKR-Regular.subset.ttf'), loadFont('NotoSansKR-Bold.subset.ttf'),
    ]);
    pm.vfs = { 'NotoSansKR-Regular.ttf': regular, 'NotoSansKR-Bold.ttf': bold };
    pm.fonts = {
      [FONT_REGULAR]: {
        normal: 'NotoSansKR-Regular.ttf', bold: 'NotoSansKR-Bold.ttf',
        italics: 'NotoSansKR-Regular.ttf', bolditalics: 'NotoSansKR-Bold.ttf',
      },
    };
    return pm;
  })();
  pdfMakePromise.catch(() => { pdfMakePromise = null; });
  return pdfMakePromise;
}

export async function makeToolListPdf(
  rows: readonly PdfRow[], metadata: Partial<ProgramMetadata> | null, lathe: boolean,
): Promise<{ bytes: Uint8Array; filename: string }> {
  const pm = await pdfMake();
  const def = buildPdfDefinition(rows, metadata, lathe);
  const bytes: Uint8Array = await new Promise((resolve, reject) => {
    try {
      pm.createPdf(def).getBuffer((buf: Uint8Array) => resolve(buf));
    } catch (error) {
      reject(error);
    }
  });
  return { bytes, filename: defaultPdfFilename(metadata ?? {}) };
}
