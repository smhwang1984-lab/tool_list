"""v2.7.0: 오픈소스 라이선스 고지 — About 버튼과 빌드 동봉, 고지문 내용을 확인한다."""

import inspect
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import third_party_notices as tpn  # noqa: E402


class ThirdPartyNoticesTest(unittest.TestCase):
    def test_components_cover_bundled_imports(self):
        names = {c[0] for c in tpn.COMPONENTS}
        for required in ('Python', 'PyQt5', 'Qt 5', 'pyqtgraph', 'NumPy', 'Numba', 'llvmlite',
                         'ModernGL', 'glcontext', 'PyOpenGL', 'ReportLab', 'PyInstaller', 'Inno Setup'):
            self.assertIn(required, names)

    def test_summary_lines_name_license(self):
        lines = tpn.summary_lines()
        self.assertEqual(len(lines), len(tpn.COMPONENTS))
        self.assertTrue(all(' — ' in line for line in lines))
        self.assertTrue(any(line.startswith('PyQt5 — GPL-3.0') for line in lines))

    def test_notice_text_contains_installed_license_texts(self):
        text = tpn.build_notice_text()
        self.assertIn('구성 요소 요약', text)
        # numpy는 테스트 환경에 항상 있다 — 원문(BSD)이 실제 파일에서 들어와야 한다.
        self.assertIn('numpy', text)
        self.assertIn('Redistribution and use in source and binary forms', text)

    def test_write_bundle_and_load(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = tpn.write_notice_bundle(os.path.join(tmp, 'licenses'))
            self.assertTrue(path.is_file())
            self.assertEqual(path.name, tpn.NOTICE_FILE_NAME)
            self.assertIn('Sum Path', path.read_text(encoding='utf-8'))

    def test_load_without_bundle_builds_live_text(self):
        self.assertIn('구성 요소 요약', tpn.load_notice_text())

    def test_spec_bundles_notice_file(self):
        spec = Path(__file__).resolve().parents[1].joinpath('NC_Tool_List.spec').read_text(encoding='utf-8-sig')
        self.assertIn('third_party_notices.write_notice_bundle', spec)
        self.assertIn("'third_party_notices'", spec)


class AboutButtonTest(unittest.TestCase):
    def test_about_has_notice_button(self):
        import NC_Tool_List as app
        source = inspect.getsource(app.App.show_about)
        self.assertIn('오픈소스 라이선스 고지...', source)
        self.assertIn('third_party_notices.summary_lines()', source)
        self.assertTrue(hasattr(app.App, 'show_third_party_notices'))


if __name__ == '__main__':
    unittest.main()
