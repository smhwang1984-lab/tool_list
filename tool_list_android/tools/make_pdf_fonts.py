"""Noto Sans KR(가변, OFL)에서 PDF용 Regular/Bold 부분 글꼴을 만든다.
사용: python tools/make_pdf_fonts.py C:/dev/fontwork/NotoSansKR-VF.ttf
출력: public/fonts/NotoSansKR-Regular.subset.ttf, NotoSansKR-Bold.subset.ttf
글자: 한글 음절 전체(U+AC00~D7A3) + 자모 + ASCII + 라틴 확장 일부 + 기호(도·℃·㎜·±·×·ø·Ø 등) + 한자 없음
"""
import sys
from pathlib import Path

from fontTools import subset
from fontTools.ttLib import TTFont
from fontTools.varLib import instancer

src = Path(sys.argv[1])
out_dir = Path(__file__).resolve().parents[1] / 'public' / 'fonts'
out_dir.mkdir(parents=True, exist_ok=True)

codepoints = set()
codepoints.update(range(0x20, 0x7F))            # ASCII
codepoints.update(range(0xA0, 0x180))           # 라틴-1/확장 A (ø Ø ° ± × µ 등)
codepoints.update(range(0x2000, 0x2070))        # 일반 문장부호(– — ‘ ’ “ ” • …)
codepoints.update(range(0x2100, 0x2200))        # ℃ № 등 글자꼴 기호, 화살표 일부
codepoints.update(range(0x2200, 0x2300))        # 수학 기호 (≤ ≥ ± ∅ ⌀ …)
codepoints.update(range(0x25A0, 0x2600))        # ■ □ ▲ ● 등
codepoints.update(range(0x3000, 0x3040))        # CJK 기호(・ 、 。 「 」)
codepoints.update(range(0x3130, 0x3190))        # 한글 호환 자모
codepoints.update(range(0x3200, 0x3300))        # ㉠ ㈜ ㎜ ㎝ ㎏ 등 호환 기호
codepoints.update(range(0x1100, 0x1200))        # 한글 자모
codepoints.update(range(0xAC00, 0xD7A4))        # 한글 음절 11,172자
codepoints.update(range(0xFF01, 0xFF5F))        # 전각 ASCII

for weight, name in ((400, 'Regular'), (700, 'Bold')):
    font = TTFont(str(src))
    inst = instancer.instantiateVariableFont(font, {'wght': weight}, inplace=False)
    options = subset.Options()
    options.layout_features = ['kern']
    options.name_IDs = [1, 2, 4, 6]
    options.notdef_outline = True
    options.hinting = False
    options.desubroutinize = True
    sub = subset.Subsetter(options)
    sub.populate(unicodes=sorted(codepoints))
    sub.subset(inst)
    target = out_dir / ('NotoSansKR-%s.subset.ttf' % name)
    inst.save(str(target))
    print(target.name, target.stat().st_size)
