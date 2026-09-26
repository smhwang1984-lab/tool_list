"""lathe_insert_spec.py(선반 인서트·홀더 규격표, v2.1.0) 테스트 + 툴리스트 통합.

- 규격 해석(ISO 1832/5608)과 종류·방향 추천, 값 우선순위, 직접 입력 저장소는 Qt 없이 검증한다.
- 툴리스트 통합(파서 열, 태그, G76 피치, 표 툴팁, 수정 값 저장/전파)은 App 창으로 검증하되
  실제 설정 폴더(APPDATA)나 장비 설정(레지스트리)을 건드리지 않는다."""
import json
import os
import sys
import tempfile
import unittest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import lathe_insert_spec as spec


class InsertParseTests(unittest.TestCase):
    """ISO 1832 — 알려진 실제 코드의 표준 값."""

    CASES = (
        # 코드, 형상, 날끝각, 여유각, 내접원, 두께, 노즈R
        ('CNMG120408', 'C', 80.0, 0.0, 12.7, 4.76, 0.8),
        ('CNMG 120404', 'C', 80.0, 0.0, 12.7, 4.76, 0.4),
        ('CNMG190612', 'C', 80.0, 0.0, 19.05, 6.35, 1.2),
        ('DNMG150404', 'D', 55.0, 0.0, 12.7, 4.76, 0.4),
        ('DCMT11T304', 'D', 55.0, 7.0, 9.525, 3.97, 0.4),
        ('DCMT070204', 'D', 55.0, 7.0, 6.35, 2.38, 0.4),
        ('TNMG160404', 'T', 60.0, 0.0, 9.525, 4.76, 0.4),
        ('TNMG220408', 'T', 60.0, 0.0, 12.7, 4.76, 0.8),
        ('TCMT110204', 'T', 60.0, 7.0, 6.35, 2.38, 0.4),
        ('VNMG160408', 'V', 35.0, 0.0, 9.525, 4.76, 0.8),
        ('VBMT110304', 'V', 35.0, 5.0, 6.35, 3.18, 0.4),
        ('WNMG080408', 'W', 80.0, 0.0, 12.7, 4.76, 0.8),
        ('WNMG060408', 'W', 80.0, 0.0, 9.525, 4.76, 0.8),
        ('SNMG120408', 'S', 90.0, 0.0, 12.7, 4.76, 0.8),
        ('SNMG090308', 'S', 90.0, 0.0, 9.525, 3.18, 0.8),
        ('CCMT09T304', 'C', 80.0, 7.0, 9.525, 3.97, 0.4),
        ('CPMH090308', 'C', 80.0, 11.0, 9.525, 3.18, 0.8),
    )

    def test_known_inserts(self):
        for code, shape, angle, clearance, ic, thickness, nose in self.CASES:
            info = spec.parse_insert(code)
            self.assertIsNotNone(info, code)
            self.assertEqual(info['shape'], shape, code)
            self.assertEqual(info['angle'], angle, code)
            self.assertEqual(info['clearance_angle'], clearance, code)
            self.assertAlmostEqual(info['ic'], ic, places=3, msg=code)
            self.assertAlmostEqual(info['thickness'], thickness, places=2, msg=code)
            self.assertAlmostEqual(info['nose_r'], nose, places=3, msg=code)

    def test_edge_length_is_computed_from_geometry(self):
        # CNMG 120408: 12.7 / sin80° = 12.9, TNMG 160404: 9.525 * sqrt(3) = 16.5
        self.assertAlmostEqual(spec.parse_insert('CNMG120408')['edge_length'], 12.9, places=1)
        self.assertAlmostEqual(spec.parse_insert('TNMG160404')['edge_length'], 16.5, places=1)
        self.assertAlmostEqual(spec.parse_insert('WNMG080408')['edge_length'], 8.7, places=1)
        self.assertAlmostEqual(spec.parse_insert('SNMG120408')['edge_length'], 12.7, places=1)

    def test_round_insert_uses_metric_or_inch_by_clearance(self):
        metric = spec.parse_insert('RCMT1204MO')          # 여유각 7° — 미터계열 지름 12
        self.assertEqual(metric['ic'], 12.0)
        self.assertAlmostEqual(metric['nose_r'], 6.0)
        inch = spec.parse_insert('RNMG120400')            # 여유각 0° — 인치계열 12.7
        self.assertEqual(inch['ic'], 12.7)
        self.assertAlmostEqual(inch['nose_r'], 6.35)
        self.assertIsNone(inch['edge_length'])

    def test_ambiguous_size_reports_alternative(self):
        info = spec.parse_insert('CNMG120408')
        self.assertEqual(info['ic'], 12.7)
        self.assertIn(12.0, info['ic_alt'])

    def test_nose_radius_is_not_invented_when_code_has_none(self):
        info = spec.parse_insert('CNMG1204')
        self.assertIsNotNone(info)
        self.assertIsNone(info['nose_r'])

    def test_text_with_spaces_and_remarks(self):
        info = spec.parse_insert('T01 - CNMG 120408 | R-0.8')
        self.assertEqual(info['shape'], 'C')
        self.assertIsNone(spec.parse_insert('D50.0 X H103 T-DRILL'))
        self.assertIsNone(spec.parse_insert('PCLNR 2525M 12'))
        self.assertIsNone(spec.parse_insert(''))
        self.assertIsNone(spec.parse_insert('CNMG 1210'))     # 두께 코드가 표에 없다


class ThreadGrooveHolderParseTests(unittest.TestCase):
    def test_thread_inserts(self):
        info = spec.parse_thread_insert('16ER 1.5 ISO')
        self.assertEqual((info['side'], info['hand'], info['pitch'], info['angle']),
                         ('외경', 'R', 1.5, 60.0))
        info = spec.parse_thread_insert('16IL 1.0ISO')
        self.assertEqual((info['side'], info['hand'], info['pitch']), ('내경', 'L', 1.0))
        info = spec.parse_thread_insert('16ER 14W')            # 산 수(TPI) -> 피치 mm
        self.assertAlmostEqual(info['pitch'], 25.4 / 14, places=4)
        self.assertEqual(info['angle'], 55.0)
        partial = spec.parse_thread_insert('16ER AG60')       # 부분 프로파일은 피치를 모른다
        self.assertIsNone(partial['pitch'])
        self.assertIsNone(spec.parse_thread_insert('CNMG 120408'))

    def test_known_groove_insert_patterns(self):
        info = spec.parse_groove_insert('N123G2-0300-0004-GM')
        self.assertEqual((info['width'], info['corner_r']), (3.0, 0.4))
        self.assertEqual(spec.parse_groove_insert('MGMN300-M')['width'], 3.0)
        self.assertEqual(spec.parse_groove_insert('MGGN 200')['width'], 2.0)
        self.assertEqual(spec.parse_groove_insert('GTN-3')['width'], 3.0)
        info = spec.parse_groove_insert('GIP 3.00-0.40')
        self.assertEqual((info['width'], info['corner_r']), (3.0, 0.4))
        # 규격을 모르는 홈 인서트는 폭을 지어내지 않는다
        self.assertIsNone(spec.parse_groove_insert('MY-GROOVE INSERT'))

    def test_holder_iso_5608(self):
        holder = spec.parse_holder('PCLNR 2525M 12')
        self.assertEqual((holder['clamp'], holder['insert_shape'], holder['style'], holder['hand']),
                         ('P', 'C', 'L', 'R'))
        self.assertEqual(holder['approach_angle'], 95.0)
        self.assertEqual((holder['shank_w'], holder['shank_h'], holder['length']), (25, 25, 150))
        self.assertEqual(holder['insert_size'], 12)
        self.assertFalse(holder['is_bar'])
        self.assertEqual(spec.parse_holder('PCLNL2525M12')['hand'], 'L')
        self.assertEqual(spec.parse_holder('SVJCR 2525 M16')['approach_angle'], 93.0)
        self.assertEqual(spec.parse_holder('SDJCR 1616H11')['length'], 100)
        bar = spec.parse_holder('S25T-PCLNR 12')
        self.assertTrue(bar['is_bar'])
        self.assertIsNone(bar['shank_w'])
        self.assertIsNone(spec.parse_holder('T06 - SLEEVE'))
        self.assertIsNone(spec.parse_holder('D50.0 X H103 T-DRILL'))


class RealSampleTextTests(unittest.TestCase):
    """v2.2.0 M0 — 실제 선반 샘플(O1699/O2222/O4811/O4812)의 인서트·홀더 문구."""

    def fields(self, insert, holder=''):
        values, _sources = spec.resolve_fields(insert, holder)
        return values

    def test_spaced_iso_codes_are_parsed(self):
        info = spec.parse_insert('CNMG 12 04 08 | R-0.8')
        self.assertEqual((info['shape'], info['ic'], info['thickness'], info['nose_r']),
                         ('C', 12.7, 4.76, 0.8))
        info = spec.parse_insert('VCMT 16 04 04 | R-0.4')
        self.assertEqual((info['shape'], info['ic'], info['nose_r']), ('V', 9.525, 0.4))
        self.assertIsNone(spec.parse_insert('D50.0 X H103 T-DRILL'))

    def test_boring_bar_holders_without_dash_are_internal(self):
        for holder in ('S16R STFPR 11 - D20', 'E08K STFPR 09', 'S07J SWUBR 06-D08', 'S40T PCLNR 12 - 50'):
            self.assertTrue(spec.parse_holder(holder)['is_bar'], holder)
        self.assertEqual(self.fields('TPGT 110302 | R-0.2', 'S16R STFPR 11 - D20')['KIND'], '내경')
        self.assertEqual(self.fields('WBGT 060102 | R-0.2', 'S07J SWUBR 06-D08')['KIND'], '내경')
        self.assertFalse(spec.parse_holder('SVJCR 2525 M16')['is_bar'])          # 외경 홀더는 그대로
        self.assertEqual(self.fields('VCMT 160404', 'SVJCR 2525 M16')['KIND'], '외경')

    def test_unj_and_other_tpi_thread_forms(self):
        info = spec.parse_thread_insert('16ER 16UNJ | R-0.24')
        self.assertAlmostEqual(info['pitch'], 25.4 / 16, places=4)                # = 1.5875
        self.assertEqual((info['side'], info['hand'], info['angle']), ('외경', 'R', 60.0))
        self.assertAlmostEqual(spec.parse_thread_insert('16IR 20UNF')['pitch'], 1.27, places=3)
        self.assertEqual(spec.parse_thread_insert('16ER 1.5 ISO')['pitch'], 1.5)  # 기존 표기 그대로
        self.assertEqual(self.fields('16ER 16UNJ | R-0.24', 'SER 2525 M16')['KIND'], '외경나사')

    def test_milling_and_center_tools_and_non_cutting_tools(self):
        cases = (
            ('D50.0 X H103 T-DRILL', 'SLEEVE', '드릴', '50'),
            ('D12 CARBIDE DRILL', 'ER25', '드릴', '12'),
            ('D1.5 CENTER', 'ER25-75', '드릴', '1.5'),
            ('D10 X 90 NC DRILL', 'MILL TOOL CHECK', '드릴', '10'),
            ('D5.5 CARBIDE DRILL, ANGLE', 'MILL TOOL CHECK', '드릴', '5.5'),
            ('D16 FLAT END MILL, ANGLE', 'MILL TOOL CHECK', '엔드밀', '16'),
            ('D12 X R1.5 FILLET END MILL', 'ER25', '엔드밀', '12'),
            ('D50. FACE CUTTER, STRAIGHT | R-0.8', 'MILL TOOL CHECK', '페이스커터', '50'),
            ('D10.SETTING PIN | R-0.', 'ER25', '비절삭', '10'),
            ('ROLLE NULLING  | R-0.12', 'NULLING TOOL', '비절삭', ''),
        )
        for insert, holder, kind, diameter in cases:
            values = self.fields(insert, holder)
            self.assertEqual((values['KIND'], values['D']), (kind, diameter), insert)
        # 종류를 못 정하는 밀링 공구(MTI ...)도 지름은 읽는다 — 종류는 사용자가 정한다
        values = self.fields('MTI 0808 D30 A60 MT8, STRAIGHT', 'MILL TOOL CHECK')
        self.assertEqual((values['KIND'], values['D']), ('', '30'))
        # 문구가 없는 R 0("R-0.")은 값이 아니다
        self.assertEqual(self.fields('D10.SETTING PIN | R-0.', 'ER25')['R'], '')

    def test_milling_tool_type_mapping_for_the_simulation(self):
        self.assertEqual(spec.mill_type_for('드릴'), 'DRILL')
        self.assertEqual(spec.mill_type_for('페이스커터', 'D50. FACE CUTTER'), 'FACE MILL')
        self.assertEqual(spec.mill_type_for('엔드밀', 'D16 FLAT END MILL'), 'FLAT E/M')
        self.assertEqual(spec.mill_type_for('엔드밀', 'D6 BALL END MILL'), 'BALL E/M')
        self.assertEqual(spec.mill_type_for('엔드밀', 'D12 X R1.5 FILLET END MILL'), 'FILLET E/M')
        self.assertIsNone(spec.mill_type_for('외경'))

    def test_tip_numbers_by_kind_and_hand(self):
        self.assertEqual(spec.infer_tip('외경', 'R'), '3')
        self.assertEqual(spec.infer_tip('외경', 'L'), '2')
        self.assertEqual(spec.infer_tip('내경', 'R'), '4')
        self.assertEqual(spec.infer_tip('내경', 'L'), '1')
        self.assertEqual(spec.infer_tip('외경나사', 'R'), '3')
        self.assertEqual(spec.infer_tip('외경홈', 'N'), '')                 # 홈은 기준 모서리를 모른다
        self.assertEqual(spec.infer_tip('외경', ''), '')
        self.assertEqual(self.fields('CNMG 120408', 'PCLNR 2525M 12')['TIP'], '3')
        self.assertEqual(self.fields('CNMG 120408', 'PCLNL 2525M 12')['TIP'], '2')
        self.assertEqual(self.fields('DNMG150404', 'S25T-PCLNR 12')['TIP'], '4')

    def test_tags_and_saved_values_for_d_and_tip(self):
        with tempfile.TemporaryDirectory() as directory:
            store = spec.LatheSpecStore(spec.specs_path(directory))
            store.update_insert('MTI 0808 D30 A60 MT8', {'D': '32'})
            store.update_tool('MILL TOOL CHECK', 'MTI 0808 D30 A60 MT8', {'KIND': '엔드밀', 'TIP': '9'})
            values, sources = spec.resolve_fields('MTI 0808 D30 A60 MT8', 'MILL TOOL CHECK', store=store)
            self.assertEqual((values['D'], sources['D']), ('32', spec.SOURCE_SAVED))     # 저장값 > 문구
            self.assertEqual((values['KIND'], values['TIP']), ('엔드밀', '9'))
        text = 'D10 X 90 NC DRILL [D 9.8]'
        self.assertEqual(spec.find_tags(text), {'D': '9.8'})
        values, sources = spec.resolve_fields(spec.strip_tags(text), '', tags=spec.find_tags(text))
        self.assertEqual((values['D'], sources['D']), ('9.8', spec.SOURCE_TAG))          # 태그 > 문구
        self.assertEqual(spec.strip_tags(text), 'D10 X 90 NC DRILL')

    def test_geometry_carries_diameter_so_and_tip(self):
        geometry = spec.geometry_from_row({
            'INSERT': 'D12 CARBIDE DRILL', 'HOLDER': 'ER25', 'KIND': '드릴', 'D': '12', 'SO': '40', 'TIP': ''})
        self.assertEqual((geometry['diameter'], geometry['so'], geometry['mill_type'], geometry['tip']),
                         (12.0, 40.0, 'DRILL', None))
        geometry = spec.geometry_from_row({'INSERT': 'CNMG 120408', 'HOLDER': 'PCLNR 2525M 12',
                                           'KIND': '외경', 'DIR': 'R', 'TIP': '3'})
        self.assertEqual((geometry['tip'], geometry['so'], geometry['diameter']), (3, None, None))


class ReviewRegressionTests(unittest.TestCase):
    """코드 리뷰에서 나온 결함이 다시 생기지 않게 고정한다."""

    def test_holder_code_is_found_after_a_leading_english_word(self):
        # 'BORING'의 앞 5글자가 먼저 걸려 진짜 홀더 코드를 놓치던 문제
        holder = spec.parse_holder('BORING BAR PCLNR 2525')
        self.assertIsNotNone(holder)
        self.assertEqual((holder['style'], holder['hand'], holder['approach_angle']), ('L', 'R', 95.0))
        values, _sources = spec.resolve_fields('DNMG 150404', 'BORING BAR S25T-PCLNR 12')
        self.assertEqual((values['KIND'], values['DIR']), ('내경', 'R'))

    def test_nose_code_00_is_not_turned_into_zero_radius(self):
        info = spec.parse_insert('CNMG 120400')
        self.assertIsNotNone(info)
        self.assertIsNone(info['nose_r'])
        values, _sources = spec.resolve_fields('CNMG 120400', '')
        self.assertEqual(values['R'], '')
        self.assertIsNone(spec.geometry_from_row({'INSERT': 'CNMG 120400'})['nose_r'])
        self.assertEqual(spec.parse_insert('RNMG120400')['ic'], 12.7)     # 원형은 여전히 IC/2

    def test_parse_results_are_cached_but_callers_get_copies(self):
        first = spec.parse_insert('CNMG 120408')
        first['nose_r'] = 99.0                                            # 호출자가 고쳐도
        first['ic_alt'] = ('x',)
        again = spec.parse_insert('CNMG 120408')
        self.assertEqual(again['nose_r'], 0.8)                            # 캐시는 오염되지 않는다
        self.assertEqual(again['ic'], 12.7)
        self.assertIsNone(spec.parse_insert('nothing here'))
        self.assertIsNone(spec.parse_holder(None))

    def test_store_falls_back_to_holder_name_when_insert_is_empty(self):
        with tempfile.TemporaryDirectory() as directory:
            store = spec.LatheSpecStore(spec.specs_path(directory))
            store.update_insert('', {'T': '3'}, 'MGEHR 2525-3')
            store.save()
            again = spec.LatheSpecStore(spec.specs_path(directory))
            self.assertEqual(again.get_insert('', 'mgehr  2525-3'), {'T': '3'})
            values, sources = spec.resolve_fields('', 'MGEHR 2525-3', store=again)
            self.assertEqual((values['T'], sources['T']), ('3', spec.SOURCE_SAVED))
            self.assertEqual(again.get_insert('', 'OTHER HOLDER'), {})     # 다른 홀더와 섞이지 않는다
            self.assertEqual(spec.LatheSpecStore.insert_key('', ''), '')    # 둘 다 비면 키 없음
            again.update_insert('', {'T': '9'}, '')
            self.assertEqual(again.get_insert('', ''), {})


class KindDirectionTests(unittest.TestCase):
    def test_kind_by_structure(self):
        self.assertEqual(spec.infer_kind('CNMG 120408', 'PCLNR 2525M 12'), '외경')
        self.assertEqual(spec.infer_kind('DNMG150404', 'S25T-PCLNR 12'), '내경')
        self.assertEqual(spec.infer_kind('16ER 1.5 ISO', 'SER 2525M16'), '외경나사')
        self.assertEqual(spec.infer_kind('16IR 1.5 ISO', 'SIR 0016 M16'), '내경나사')
        self.assertEqual(spec.infer_kind('N123G2-0300-0004-GM', 'MGEHR 2525-3'), '외경홈')
        self.assertEqual(spec.infer_kind('MGMN300-M', 'S25T-MGEHR 3'), '내경홈')

    def test_kind_by_keyword(self):
        self.assertEqual(spec.infer_kind('D50.0 X H103 T-DRILL', 'SLEEVE'), '드릴')
        self.assertEqual(spec.infer_kind('', '드릴 홀더'), '드릴')
        self.assertEqual(spec.infer_kind('CUT-OFF 3MM', ''), '절단')
        self.assertEqual(spec.infer_kind('정면 홈 3', ''), '정면홈')
        self.assertEqual(spec.infer_kind('내경 홈', ''), '내경홈')

    def test_kind_from_program_hints_only_when_text_says_nothing(self):
        hints = spec.program_hints(['G0 X50. Z5.', 'G76 P010060 Q100', 'G76 X47.5 Z-30. F1.5'])
        self.assertTrue(hints['thread'])
        self.assertEqual(spec.infer_kind('', '', hints), '외경나사')
        self.assertEqual(spec.infer_kind('CNMG 120408', '', hints), '외경')    # 문구가 우선
        self.assertEqual(spec.infer_kind('', '', spec.program_hints(['G75 R0.5'])), '외경홈')
        self.assertEqual(spec.infer_kind('', '', spec.program_hints(['G74 R0.5'])), '정면홈')
        self.assertEqual(spec.infer_kind('', '', spec.program_hints(['G71 U1. R0.5'])), '외경')
        self.assertEqual(spec.infer_kind('', ''), '')

    def test_direction(self):
        self.assertEqual(spec.infer_direction('외경', 'CNMG 120408', 'PCLNR 2525M 12'), 'R')
        self.assertEqual(spec.infer_direction('외경', 'CNMG 120408', 'PCLNL 2525M 12'), 'L')
        self.assertEqual(spec.infer_direction('외경', 'VNMG160404', 'MVJNL 2525M16'), 'L')
        self.assertEqual(spec.infer_direction('외경나사', '16EL 1.5 ISO', ''), 'L')       # 나사 인서트 손
        self.assertEqual(spec.infer_direction('외경홈', 'N123G2-0300-0004-GM', 'MGEHL 2525-3'), 'L')
        self.assertEqual(spec.infer_direction('절단', 'CUT-OFF', ''), 'N')
        self.assertEqual(spec.infer_direction('드릴', '', ''), 'N')
        self.assertEqual(spec.infer_direction('외경', 'CNMG 120408', ''), '')               # 모르면 비움


class ProgramHintTests(unittest.TestCase):
    def test_thread_pitch_from_g76_and_g32(self):
        hints = spec.program_hints(['G0X50.Z5.', 'G76P010060Q100R0.05', 'G76X47.5Z-30.P920Q300F1.5'])
        self.assertEqual(hints['pitch'], '1.5')
        self.assertEqual(spec.program_hints(['G32 Z-20. F2.0'])['pitch'], '2')
        self.assertEqual(spec.program_hints(['G1 Z-20. F0.2'])['pitch'], '')          # 일반 이송은 피치 아님
        self.assertEqual(spec.program_hints(['G76 X47.5 Z-30. F800.'])['pitch'], '')  # 범위 밖(mm/min 등)

    def test_pitch_uses_only_the_f_word_on_the_thread_line(self):
        """나사 블록 뒤 다른 줄의 이송 F를 피치로 읽던 문제."""
        hints = spec.program_hints(['G32 Z-30.', 'G00 X50.', 'G01 X60. F0.3'])
        self.assertTrue(hints['thread'])
        self.assertEqual(hints['pitch'], '')
        hints = spec.program_hints(['G76 P010060 Q100 R0.05', 'G01 X60. F0.3', 'G76 X47.5 Z-30. F1.5'])
        self.assertEqual(hints['pitch'], '1.5')                         # 둘째 G76 줄의 F

    def test_merge_keeps_first_pitch(self):
        first = spec.program_hints(['G32 Z-20. F2.0'])
        second = spec.program_hints(['G32 Z-20. F1.0', 'G75 R0.5'])
        merged = spec.merge_hints(first, second)
        self.assertEqual(merged['pitch'], '2')
        self.assertTrue(merged['thread'] and merged['groove'])


class ResolvePriorityTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.store = spec.LatheSpecStore(spec.specs_path(self.dir.name))

    def test_r_priority_tag_then_saved_then_text_then_iso(self):
        insert = 'CNMG 120408'
        values, sources = spec.resolve_fields(insert, '')
        self.assertEqual((values['R'], sources['R']), ('0.8', spec.SOURCE_ISO))
        values, sources = spec.resolve_fields('CNMG 120408 | R-1.2', '')
        self.assertEqual((values['R'], sources['R']), ('1.2', spec.SOURCE_TEXT))     # 문구가 ISO보다 우선
        self.store.update_insert(insert, {'R': '0.5'})
        values, sources = spec.resolve_fields(insert, '', store=self.store)
        self.assertEqual((values['R'], sources['R']), ('0.5', spec.SOURCE_SAVED))     # 저장값이 문구/ISO보다 우선
        values, sources = spec.resolve_fields(insert, '', tags={'R': '0.2'}, store=self.store)
        self.assertEqual((values['R'], sources['R']), ('0.2', spec.SOURCE_TAG))       # 태그가 가장 우선

    def test_pitch_priority_tag_insert_program_saved(self):
        insert = '16ER AG60'                                   # 부분 프로파일 — 피치 표기 없음
        hints = {'pitch': '1.5', 'thread': True}
        self.store.update_insert(insert, {'PITCH': '3'})
        values, sources = spec.resolve_fields(insert, '', hints=hints, store=self.store)
        self.assertEqual((values['PITCH'], sources['PITCH']), ('1.5', spec.SOURCE_PROGRAM))
        values, sources = spec.resolve_fields(insert, '', store=self.store)             # 프로그램이 없으면 저장값
        self.assertEqual((values['PITCH'], sources['PITCH']), ('3', spec.SOURCE_SAVED))
        values, sources = spec.resolve_fields('16ER 1.0 ISO', '', hints=hints)          # 인서트 표기가 프로그램보다 우선
        self.assertEqual((values['PITCH'], sources['PITCH']), ('1', spec.SOURCE_INSERT))
        values, sources = spec.resolve_fields('16ER 1.0 ISO', '', tags={'PITCH': '2'}, hints=hints)
        self.assertEqual((values['PITCH'], sources['PITCH']), ('2', spec.SOURCE_TAG))

    def test_groove_width_when_spec_is_unknown_stays_blank_until_entered(self):
        insert = 'MY-GROOVE INSERT'
        values, _sources = spec.resolve_fields(insert, 'MGEHR 2525-3')
        self.assertEqual(values['T'], '')                                              # 지어내지 않는다
        self.store.update_insert(insert, {'T': '3.2'})
        values, sources = spec.resolve_fields(insert, 'MGEHR 2525-3', store=self.store)
        self.assertEqual((values['T'], sources['T']), ('3.2', spec.SOURCE_SAVED))
        values, sources = spec.resolve_fields('N123G2-0300-0004-GM', '')                 # 규격을 알면 자동
        self.assertEqual((values['T'], sources['T']), ('3', spec.SOURCE_ISO))

    def test_saved_kind_and_direction_beat_auto_and_are_per_holder_insert_pair(self):
        holder, insert = 'PCLNR 2525M 12', 'CNMG 120408'
        self.store.update_tool(holder, insert, {'KIND': '내경', 'DIR': 'L'})
        values, sources = spec.resolve_fields(insert, holder, store=self.store)
        self.assertEqual((values['KIND'], values['DIR']), ('내경', 'L'))
        self.assertEqual(sources['KIND'], spec.SOURCE_SAVED)
        # 같은 인서트라도 홀더가 다르면 자동 추천
        values, sources = spec.resolve_fields(insert, 'S25T-PCLNR 12', store=self.store)
        self.assertEqual((values['KIND'], sources['KIND']), ('내경', spec.SOURCE_AUTO))
        values, _sources = spec.resolve_fields(insert, 'PCLNL 2525M 12', store=self.store)
        self.assertEqual((values['KIND'], values['DIR']), ('외경', 'L'))

    def test_tags_are_found_and_stripped(self):
        text = 'CNMG 120408 [R 0.4] [T 3.0] [P 1.5]'
        self.assertEqual(spec.find_tags(text), {'R': '0.4', 'T': '3', 'PITCH': '1.5'})
        self.assertEqual(spec.strip_tags(text), 'CNMG 120408')
        self.assertEqual(spec.find_tags('[SO 40] PCLNR'), {})                            # SO는 태그가 아님
        self.assertEqual(spec.normalize_key(' cnmg  120408 [R 0.4] '), 'CNMG 120408')


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.path = spec.specs_path(self.dir.name)

    def test_round_trip_and_key_normalization(self):
        store = spec.LatheSpecStore(self.path)
        store.update_insert('cnmg  120408', {'R': '0.5', 'T': '', 'PITCH': ' '})
        store.update_tool('PCLNR 2525M 12', 'CNMG 120408', {'KIND': '외경', 'DIR': 'R'})
        store.save()
        again = spec.LatheSpecStore(self.path)
        self.assertEqual(again.get_insert('CNMG 120408 [R 9]'), {'R': '0.5'})
        self.assertEqual(again.get_tool('pclnr 2525m 12', 'cnmg 120408'), {'KIND': '외경', 'DIR': 'R'})
        with open(self.path, encoding='utf-8') as fp:
            self.assertEqual(json.load(fp)['version'], 1)

    def test_empty_values_delete_and_empty_entries_disappear(self):
        store = spec.LatheSpecStore(self.path)
        store.update_insert('CNMG 120408', {'R': '0.5', 'T': '3'})
        store.update_insert('CNMG 120408', {'R': ''})
        self.assertEqual(store.get_insert('CNMG 120408'), {'T': '3'})
        store.update_insert('CNMG 120408', {'T': ''})
        self.assertNotIn('CNMG 120408', store.insert)
        store.update_insert('', {'R': '1'})                       # 이름 없는 인서트는 저장하지 않는다
        store.update_tool('', '', {'KIND': '외경'})
        self.assertEqual((store.insert, store.tool), ({}, {}))

    def test_missing_or_broken_file_is_tolerated(self):
        self.assertEqual(spec.LatheSpecStore(self.path).insert, {})
        with open(self.path, 'w', encoding='utf-8') as fp:
            fp.write('{ not json')
        self.assertEqual(spec.LatheSpecStore(self.path).insert, {})
        with open(self.path, 'w', encoding='utf-8') as fp:
            json.dump({'insert': {'A': 'text', 'B': {'R': '1', 'X': '9'}}, 'tool': []}, fp)
        store = spec.LatheSpecStore(self.path)
        self.assertEqual(store.insert, {'B': {'R': '1'}})        # 알 수 없는 필드/형식은 버린다

    def test_store_without_path_never_writes(self):
        store = spec.LatheSpecStore(None)
        store.update_insert('CNMG 120408', {'R': '0.5'})
        store.save()                                              # 오류 없이 무시


class GeometryMapTests(unittest.TestCase):
    def test_geometry_map_keys_and_values(self):
        rows = [
            {'NO': 'T0101', 'INSERT': 'CNMG 120408', 'R': '0.8', 'T': '', 'PITCH': '',
             'HOLDER': 'PCLNR 2525M 12', 'KIND': '외경', 'DIR': 'R'},
            {'NO': 'T0111', 'INSERT': 'CNMG 120404', 'R': '0.4', 'HOLDER': 'PCLNR 2525M 12',
             'KIND': '외경', 'DIR': 'R'},                          # 같은 공구번호 — 먼저 나온 행이 이긴다
            {'NO': 'T0303', 'INSERT': '16ER AG60', 'R': '', 'T': '', 'PITCH': '1.5',
             'HOLDER': 'SER 2525M16', 'KIND': '외경나사', 'DIR': 'R'},
            {'NO': 'T0404', 'INSERT': 'MY-GROOVE', 'T': '3.2', 'KIND': '외경홈', 'DIR': 'N'},
            {'NO': ''},
        ]
        mapping = spec.geometry_map_from_rows(rows)
        self.assertEqual(set(mapping), {'T01', 'T1', '1', 'T03', 'T3', '3', 'T04', 'T4', '4'})
        turn = mapping['T01']
        self.assertEqual((turn['kind'], turn['hand'], turn['nose_r']), ('외경', 'R', 0.8))
        self.assertEqual((turn['shape'], turn['tip_angle'], turn['ic']), ('C', 80.0, 12.7))
        self.assertEqual(turn['approach_angle'], 95.0)
        self.assertEqual(turn['shank'], (25, 25))
        thread = mapping['T3']
        self.assertEqual((thread['kind'], thread['pitch'], thread['thread_angle']), ('외경나사', 1.5, 60.0))
        groove = mapping['4']
        self.assertEqual((groove['width'], groove['nose_r'], groove['ic']), (3.2, None, None))

    def test_geometry_falls_back_to_iso_values_when_cells_are_blank(self):
        geometry = spec.geometry_from_row({'INSERT': 'N123G2-0300-0004-GM', 'HOLDER': 'MGEHR 2525-3'})
        self.assertEqual((geometry['width'], geometry['nose_r']), (3.0, 0.4))
        geometry = spec.geometry_from_row({'INSERT': 'CNMG 120408', 'HOLDER': 'PCLNL 2525M 12'})
        self.assertEqual((geometry['nose_r'], geometry['hand']), (0.8, 'L'))


class DescribeTests(unittest.TestCase):
    def test_tooltips_summarise_the_parse(self):
        text = spec.describe_insert('CNMG 120408')
        for expected in ('ISO 1832', '80° 마름모', '내접원 12.7', '두께 4.76', '노즈R 0.8'):
            self.assertIn(expected, text)
        self.assertIn('피치 1.5', spec.describe_insert('16ER 1.5 ISO'))
        self.assertIn('폭 3', spec.describe_insert('MGMN300-M'))
        self.assertEqual(spec.describe_insert('D50.0 X H103 T-DRILL'), '')
        holder = spec.describe_holder('PCLNR 2525M 12')
        for expected in ('ISO 5608', '접근각 95°', '우수(R)', '섕크 25×25', '길이 150'):
            self.assertIn(expected, holder)
        self.assertEqual(spec.describe_holder('SLEEVE'), '')


# ---------------------------------------------------------------------------
# 툴리스트 통합
# ---------------------------------------------------------------------------

import NC_Tool_List as app

LATHE_SOURCE = """N1
( T01 - SER 2525M16 [R 0.1] )
( T01 - 16ER AG60 [SO 40] )
G0X400.Z200.
T0100
G97S800M3
T0101
G0X50.Z5.
G76 P010060 Q100 R0.05
G76 X47.5 Z-30. P920 Q300 F1.5
G0X400.Z200.T0100
M1

N2
( T02 - MGEHR 2525-3 )
( T02 - N123G2-0300-0004-GM [T 3.2] )
T0202
G75 R0.5
G75 X30. P500 F0.1
M1

N3
( T03 - PCLNR 2525M 12 )
( T03 - CNMG 120408 )
T0303
G71 U1. R0.5
M1

N4
( T04 - PCLNR 2525M 12 )
( T04 - CNMG 120408 )
T0404
G71 U1. R0.5
M1

N5
( T05 - S25T-MGEHR 3 )
( T05 - MY-GROOVE INSERT )
T0505
G75 R0.5
M1
"""


class LatheParserIntegrationTests(unittest.TestCase):
    def rows(self, store=None):
        return {row['NO']: row for row in app.parse_lathe_program(LATHE_SOURCE, store) if row['NO']}

    def test_new_columns_are_filled_from_tags_iso_and_program(self):
        rows = self.rows()
        thread = rows['T0101']
        self.assertEqual((thread['R'], thread['PITCH'], thread['SO']), ('0.1', '1.5', '40'))
        self.assertEqual((thread['KIND'], thread['DIR']), ('외경나사', 'R'))
        self.assertEqual(thread.sources['R'], spec.SOURCE_TAG)
        self.assertEqual(thread.sources['PITCH'], spec.SOURCE_PROGRAM)     # 인서트에 피치 표기가 없어 프로그램 F
        groove = rows['T0202']
        self.assertEqual((groove['R'], groove['T']), ('0.4', '3.2'))        # T는 태그, R은 ISO 해석
        self.assertEqual((groove['KIND'], groove['DIR']), ('외경홈', 'R'))
        turn = rows['T0303']
        self.assertEqual((turn['R'], turn['T'], turn['PITCH']), ('0.8', '', ''))
        self.assertEqual((turn['KIND'], turn['DIR']), ('외경', 'R'))
        unknown = rows['T0505']                                             # 규격을 못 찾는 홈 인서트
        self.assertEqual((unknown['R'], unknown['T'], unknown['PITCH']), ('', '', ''))
        self.assertEqual(unknown['KIND'], '내경홈')                         # 홀더가 내경 바(S25T-...)

    def test_tags_are_stripped_from_display_text_but_so_still_works(self):
        rows = self.rows()
        self.assertEqual(rows['T0101']['HOLDER'], 'SER 2525M16')
        self.assertEqual(rows['T0101']['INSERT'], '16ER AG60')
        self.assertEqual(rows['T0202']['INSERT'], 'N123G2-0300-0004-GM')

    def test_rows_stay_plain_dict_compatible(self):
        row = self.rows()['T0303']
        self.assertIsInstance(row, dict)
        self.assertEqual(set(row), {key for key, _label in app.LATHE_COLUMNS})

    def test_saved_values_apply_on_parse(self):
        with tempfile.TemporaryDirectory() as directory:
            store = spec.LatheSpecStore(spec.specs_path(directory))
            store.update_insert('MY-GROOVE INSERT', {'T': '2.5', 'R': '0.2'})
            store.update_tool('S25T-MGEHR 3', 'MY-GROOVE INSERT', {'KIND': '정면홈', 'DIR': 'L'})
            row = self.rows(store)['T0505']
            self.assertEqual((row['T'], row['R'], row['KIND'], row['DIR']), ('2.5', '0.2', '정면홈', 'L'))
            self.assertEqual(row.sources['KIND'], spec.SOURCE_SAVED)
            self.assertEqual(row.sources['T'], spec.SOURCE_SAVED)

    def test_existing_milling_columns_are_untouched(self):
        self.assertEqual(len(app.COLUMNS), 16)
        self.assertNotIn('KIND', [key for key, _label in app.COLUMNS])

    def test_pdf_layout_matches_lathe_columns(self):
        self.assertEqual(len(app.LATHE_PDF_COLUMN_WEIGHTS), len(app.LATHE_COLUMNS))
        widths = app.lathe_pdf_column_widths(780.0)
        self.assertAlmostEqual(sum(widths), 780.0)
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, 'lathe.pdf')
            app.export_lathe_tool_list_pdf(path, list(self.rows().values()), {})
            self.assertGreater(os.path.getsize(path), 1000)


@unittest.skipIf(app.QT_IMPORT_ERROR is not None, 'viewer dependencies are not available')
class LatheToolListWindowTests(unittest.TestCase):
    """표 · 툴팁 · 수정 값 저장/전파 — 장비 설정(레지스트리)은 건드리지 않는다."""

    # 앱 창(뷰어 포함)은 무겁다 — 테스트마다 새로 만들어 쌓으면 전체 실행에서 뒤쪽 테스트가 접근 위반으로
    # 죽는다(실측). 클래스당 하나만 만들어 공유하고, 테스트마다 저장소와 프로그램 내용만 초기화한다.
    @classmethod
    def setUpClass(cls):
        cls.qapp = app.QApplication.instance() or app.QApplication([])
        cls.directory = tempfile.TemporaryDirectory()
        cls.window = app.App(_root=cls.directory.name)
        cls.window.is_lathe_program = lambda: True      # 장비 콤보(저장 설정)를 바꾸지 않고 선반 모드로
        cls.window._configure_table_columns()
        cls.initial_store_path = cls.window.lathe_store.path

    @classmethod
    def tearDownClass(cls):
        cls.window.deleteLater()
        cls.qapp.processEvents()
        cls.directory.cleanup()

    def make_window(self):
        """공유 창을 처음 상태로 되돌려 준다: 빈 저장소(임시 폴더), LATHE_SOURCE로 만든 표."""
        store_dir = tempfile.TemporaryDirectory()
        self.addCleanup(store_dir.cleanup)
        window = self.window
        window.lathe_store = spec.LatheSpecStore(spec.specs_path(store_dir.name))
        window.src.setPlainText(LATHE_SOURCE)
        window.invalidate_parse_cache()
        window.run()
        window.update_count()
        return window, store_dir.name

    def row_index(self, window, tool_no):
        for index in range(window.table.rowCount()):
            if window.table_text(index, 'NO') == tool_no:
                return index
        self.fail('row %s not found' % tool_no)

    def test_store_lives_in_the_given_root_not_in_user_settings(self):
        self.assertEqual(os.path.dirname(self.initial_store_path), self.directory.name)
        self.assertEqual(os.path.basename(self.initial_store_path), 'lathe_insert_specs.json')

    def test_table_shows_new_columns_with_source_tooltips(self):
        window, _directory = self.make_window()
        self.assertEqual(window.table.columnCount(), len(app.LATHE_COLUMNS))
        labels = [window.table.horizontalHeaderItem(i).text() for i in range(window.table.columnCount())]
        self.assertEqual(labels[:6], ['TOOL NO', 'INSERT', 'R', 'T', 'PITCH', '홀더'])
        self.assertEqual(labels[6:9], ['SO', '종류', '방향'])
        index = self.row_index(window, 'T0202')
        self.assertEqual(window.table_text(index, 'T'), '3.2')
        columns = [key for key, _label in app.LATHE_COLUMNS]
        t_item = window.table.item(index, columns.index('T'))
        self.assertIn(spec.SOURCE_TAG, t_item.toolTip())
        insert_item = window.table.item(index, columns.index('INSERT'))
        self.assertIn('폭 3', insert_item.toolTip())
        holder_item = window.table.item(self.row_index(window, 'T0303'), columns.index('HOLDER'))
        self.assertIn('접근각 95°', holder_item.toolTip())
        empty_item = window.table.item(self.row_index(window, 'T0505'), columns.index('T'))
        self.assertIn('[수정]', empty_item.toolTip())                 # 비어 있으면 입력 안내

    def test_copy_table_includes_new_columns(self):
        window, _directory = self.make_window()
        window.with_header.setChecked(True)
        window.copy_table()
        header = self.qapp.clipboard().text().splitlines()[0].split('\t')
        self.assertEqual(header[:9], ['TOOL NO', 'INSERT', 'R', 'T', 'PITCH', '홀더', 'SO', '종류', '방향'])

    def test_editing_saves_only_changed_values_and_propagates_to_same_insert(self):
        window, _directory = self.make_window()
        first = self.row_index(window, 'T0303')
        second = self.row_index(window, 'T0404')                         # 같은 홀더+인서트
        original = {key: window.table_text(first, key) for key, _label in window.active_columns()}
        edited = app.LatheRow(dict(original, R='0.4', KIND='내경'))     # R은 ISO(0.8)와 다름, 종류도 변경
        edited.sources = window._row_sources(first)
        changed = window._save_lathe_spec_edits(original, edited)
        self.assertEqual(set(changed), {'R', 'KIND'})
        store = window.lathe_store
        self.assertEqual(store.get_insert('CNMG 120408'), {'R': '0.4'})
        self.assertEqual(store.get_tool('PCLNR 2525M 12', 'CNMG 120408'), {'KIND': '내경'})
        for key in changed:                                              # save()가 하는 출처 표시
            edited.sources[key] = spec.SOURCE_SAVED
        window.set_table_row(first, edited)
        window._propagate_lathe_specs(first, original, edited, changed)
        self.assertEqual(window.table_text(second, 'R'), '0.4')           # 같은 인서트의 다른 행도 갱신
        self.assertEqual(window.table_text(second, 'KIND'), '내경')
        self.assertEqual(window._row_sources(second)['R'], spec.SOURCE_SAVED)
        # 저장 파일이 실제로 써졌고, 다시 읽어도 같다
        again = spec.LatheSpecStore(store.path)
        self.assertEqual(again.get_insert('CNMG 120408'), {'R': '0.4'})
        # 프로그램을 다시 읽으면(표 재생성) 저장값이 적용된다
        window.run()
        self.assertEqual(window.table_text(self.row_index(window, 'T0303'), 'R'), '0.4')

    def test_value_equal_to_iso_recommendation_is_not_stored(self):
        window, _directory = self.make_window()
        index = self.row_index(window, 'T0303')
        original = {key: window.table_text(index, key) for key, _label in window.active_columns()}
        window.lathe_store.update_insert('CNMG 120408', {'R': '0.4'})      # 예전에 저장한 값
        edited = app.LatheRow(dict(original, R='0.8'))                     # 다시 ISO 값(0.8)으로 되돌림
        changed = window._save_lathe_spec_edits(dict(original, R='0.4'), edited)
        self.assertEqual(changed, ['R'])
        self.assertEqual(window.lathe_store.get_insert('CNMG 120408'), {})   # 저장값 삭제 -> 다시 자동

    def test_unchanged_row_writes_nothing(self):
        window, _directory = self.make_window()
        index = self.row_index(window, 'T0303')
        original = {key: window.table_text(index, key) for key, _label in window.active_columns()}
        self.assertEqual(window._save_lathe_spec_edits(original, app.LatheRow(dict(original))), [])
        self.assertFalse(os.path.exists(window.lathe_store.path))

    # -- [수정]/[행 추가] 창 자체(exec_를 대체해 실제 위젯을 조작한다) -----------------------
    def drive_dialog(self, window, action, *, row_index=None):
        """show_row_editor를 열고 action(dialog, fields)을 실행한다. fields = {열 라벨: 입력 위젯}."""
        from unittest import mock

        def fake_exec(dialog):
            layout = dialog.layout()
            fields = {}
            for i in range(layout.count()):
                widget = layout.itemAt(i).widget()
                if isinstance(widget, app.QLabel):
                    row, column, _rs, _cs = layout.getItemPosition(i)
                    fields[widget.text()] = layout.itemAtPosition(row, column + 1).widget()
            action(dialog, fields)
            return 0

        with mock.patch.object(app.QDialog, 'exec_', fake_exec):
            if row_index is None:
                window.add_row()
            else:
                window.table.selectRow(row_index)
                window.edit_selected()

    @staticmethod
    def click(dialog, text=None, standard=None):
        for button in dialog.findChildren(app.QPushButton):
            if text is not None and button.text() == text:
                button.click()
                return
            if standard is not None and dialog.findChild(app.QDialogButtonBox).button(standard) is button:
                button.click()
                return
        raise AssertionError('button not found: %s' % (text or standard))

    def test_dialog_has_kind_direction_combos_and_auto_recommendation(self):
        window, _directory = self.make_window()
        index = self.row_index(window, 'T0303')
        seen = {}

        def action(dialog, fields):
            seen['kinds'] = [fields['종류'].itemData(i) for i in range(fields['종류'].count())]
            seen['dirs'] = [fields['방향'].itemData(i) for i in range(fields['방향'].count())]
            seen['kind_now'], seen['dir_now'] = fields['종류'].currentData(), fields['방향'].currentData()
            self.assertIn('T', fields)                                      # R/T/PITCH 입력칸이 있다
            self.assertTrue(all(name in fields for name in ('R', 'T', 'PITCH')))
            fields['INSERT'].setText('DNMG150404')
            fields['R'].setText('9')                                        # 엉뚱한 값으로 바꾼 뒤
            fields['종류'].setCurrentIndex(0)
            self.click(dialog, '자동 추천')                                   # 다시 추천받는다
            seen['r_after'], seen['kind_after'] = fields['R'].text(), fields['종류'].currentData()
            self.click(dialog, standard=app.QDialogButtonBox.Save)

        self.drive_dialog(window, action, row_index=index)
        self.assertEqual(seen['kinds'], [''] + list(spec.KINDS))
        self.assertEqual(seen['dirs'], ['', 'R', 'L', 'N'])
        self.assertEqual((seen['kind_now'], seen['dir_now']), ('외경', 'R'))
        self.assertEqual((seen['r_after'], seen['kind_after']), ('0.4', '외경'))
        self.assertEqual(window.table_text(index, 'INSERT'), 'DNMG150404')
        self.assertEqual(window.table_text(index, 'R'), '0.4')

    def test_dialog_edit_is_saved_and_survives_reparse(self):
        window, _directory = self.make_window()
        index = self.row_index(window, 'T0505')

        def action(dialog, fields):
            fields['T'].setText('2.5')
            fields['종류'].setCurrentIndex(fields['종류'].findData('정면홈'))
            fields['방향'].setCurrentIndex(fields['방향'].findData('L'))
            self.click(dialog, standard=app.QDialogButtonBox.Save)

        self.drive_dialog(window, action, row_index=index)
        self.assertEqual((window.table_text(index, 'T'), window.table_text(index, 'KIND'),
                          window.table_text(index, 'DIR')), ('2.5', '정면홈', 'L'))
        columns = [key for key, _label in app.LATHE_COLUMNS]
        tip = window.table.item(index, columns.index('T')).toolTip()
        self.assertIn(spec.SOURCE_SAVED, tip)
        self.assertEqual(window.lathe_store.get_insert('MY-GROOVE INSERT'), {'T': '2.5'})
        window.run()                                                        # 표를 다시 만들어도 유지
        again = self.row_index(window, 'T0505')
        self.assertEqual((window.table_text(again, 'T'), window.table_text(again, 'KIND'),
                          window.table_text(again, 'DIR')), ('2.5', '정면홈', 'L'))

    def test_dialog_cancel_changes_nothing(self):
        window, _directory = self.make_window()
        index = self.row_index(window, 'T0505')

        def action(dialog, fields):
            fields['T'].setText('9')
            self.click(dialog, standard=app.QDialogButtonBox.Cancel)

        self.drive_dialog(window, action, row_index=index)
        self.assertEqual(window.table_text(index, 'T'), '')
        self.assertFalse(os.path.exists(window.lathe_store.path))

    def test_new_row_gets_recommended_values_automatically(self):
        window, _directory = self.make_window()
        before = window.table.rowCount()

        def action(dialog, fields):
            fields['INSERT'].setText('TNMG160404')
            fields['홀더'].setText('PCLNL 2525M 12')
            self.click(dialog, standard=app.QDialogButtonBox.Save)          # R/종류/방향은 비워 둔다

        self.drive_dialog(window, action)
        self.assertEqual(window.table.rowCount(), before + 1)
        new = window.table.rowCount() - 1
        self.assertEqual((window.table_text(new, 'R'), window.table_text(new, 'KIND'),
                          window.table_text(new, 'DIR')), ('0.4', '외경', 'L'))
        columns = [key for key, _label in app.LATHE_COLUMNS]
        self.assertIn(spec.SOURCE_ISO, window.table.item(new, columns.index('R')).toolTip())
        self.assertFalse(os.path.exists(window.lathe_store.path))           # 자동 값은 저장하지 않는다

    def test_edit_of_program_specific_value_is_kept_for_this_table_only(self):
        """태그/프로그램 값은 저장값보다 우선하므로 고쳐도 저장하지 않는다(다음 파싱에서 사라질 값을
        저장소에 쌓지 않는다) — 이번 표에서만 유지하고 그렇게 표시한다."""
        window, _directory = self.make_window()
        index = self.row_index(window, 'T0101')                       # PITCH = 프로그램 G76 F1.5, R = 태그 0.1
        self.assertEqual(window._row_sources(index)['PITCH'], spec.SOURCE_PROGRAM)

        def action(dialog, fields):
            fields['PITCH'].setText('2')
            fields['R'].setText('0.3')
            self.click(dialog, standard=app.QDialogButtonBox.Save)

        self.drive_dialog(window, action, row_index=index)
        self.assertEqual((window.table_text(index, 'PITCH'), window.table_text(index, 'R')), ('2', '0.3'))
        sources = window._row_sources(index)
        self.assertEqual((sources['PITCH'], sources['R']), (spec.SOURCE_MANUAL, spec.SOURCE_MANUAL))
        self.assertEqual(window.lathe_store.get_insert('16ER AG60'), {})     # 저장소에는 아무것도 쌓이지 않는다
        self.assertFalse(os.path.exists(window.lathe_store.path))
        self.assertIn('이번 표에서만', window.count.text())                  # 저장 직후 임시라고 알린다
        window.run()                                                      # 다시 읽으면 프로그램 값으로 돌아간다
        again = self.row_index(window, 'T0101')
        self.assertEqual((window.table_text(again, 'PITCH'), window.table_text(again, 'R')), ('1.5', '0.1'))

    def test_clearing_an_auto_recommendation_sticks_across_reparse(self):
        """잘못된 자동 추천(종류)을 지우면 다음 파싱에서 되살아나지 않고, 추천값으로 되돌리면 다시 자동."""
        window, _directory = self.make_window()
        index = self.row_index(window, 'T0303')
        self.assertEqual(window.table_text(index, 'KIND'), '외경')

        def clear(dialog, fields):
            fields['종류'].setCurrentIndex(0)
            self.click(dialog, standard=app.QDialogButtonBox.Save)

        self.drive_dialog(window, clear, row_index=index)
        self.assertEqual(window.table_text(index, 'KIND'), '')
        self.assertEqual(window.lathe_store.get_tool('PCLNR 2525M 12', 'CNMG 120408'),
                         {'KIND': spec.BLANK})
        window.run()
        self.assertEqual(window.table_text(self.row_index(window, 'T0303'), 'KIND'), '')       # 유지
        self.assertEqual(window.table_text(self.row_index(window, 'T0303'), 'DIR'), 'R')       # 다른 값은 그대로
        # 같은 홀더+인서트를 쓰는 T0404도 함께 비워진다(전파)
        self.assertEqual(window.table_text(self.row_index(window, 'T0404'), 'KIND'), '')

        def restore(dialog, fields):
            fields['종류'].setCurrentIndex(fields['종류'].findData('외경'))
            self.click(dialog, standard=app.QDialogButtonBox.Save)

        self.drive_dialog(window, restore, row_index=self.row_index(window, 'T0303'))
        self.assertEqual(window.lathe_store.get_tool('PCLNR 2525M 12', 'CNMG 120408'), {})    # 추천값과 같으면 삭제
        window.run()
        self.assertEqual(window.table_text(self.row_index(window, 'T0303'), 'KIND'), '외경')

    def test_clearing_a_value_without_recommendation_just_removes_the_saved_one(self):
        window, _directory = self.make_window()
        window.lathe_store.update_insert('MY-GROOVE INSERT', {'T': '2.5'})
        window.invalidate_parse_cache()
        window.run()
        index = self.row_index(window, 'T0505')
        self.assertEqual(window.table_text(index, 'T'), '2.5')

        def clear(dialog, fields):
            fields['T'].setText('')
            self.click(dialog, standard=app.QDialogButtonBox.Save)

        self.drive_dialog(window, clear, row_index=index)
        self.assertEqual(window.lathe_store.get_insert('MY-GROOVE INSERT'), {})     # '-'가 아니라 그냥 삭제
        window.run()
        self.assertEqual(window.table_text(self.row_index(window, 'T0505'), 'T'), '')

    def test_program_specific_edit_is_not_propagated_to_other_rows(self):
        window, _directory = self.make_window()
        window.src.setPlainText(LATHE_SOURCE + """
N9
( T09 - SER 2525M16 )
( T09 - 16ER AG60 )
T0909
G32 Z-20. F1.0
M1
""")
        window.run()
        first = self.row_index(window, 'T0101')                        # PITCH 1.5 (G76)
        other = self.row_index(window, 'T0909')                        # PITCH 1 (G32)
        self.assertEqual(window.table_text(other, 'PITCH'), '1')
        original = {key: window.table_text(first, key) for key, _label in window.active_columns()}
        edited = app.LatheRow(dict(original, PITCH='2'))
        edited.sources = window._row_sources(first)
        changed = window._save_lathe_spec_edits(original, edited)
        self.assertEqual(edited.sources['PITCH'], spec.SOURCE_MANUAL)
        window._propagate_lathe_specs(first, original, edited, changed)
        self.assertEqual(window.table_text(other, 'PITCH'), '1')          # 다른 행은 자기 프로그램 값 그대로

    def test_propagation_does_not_overwrite_rows_whose_value_comes_from_their_own_tag(self):
        window, _directory = self.make_window()
        window.src.setPlainText("""N1
( T01 - PCLNR 2525M 12 )
( T01 - CNMG 120408 [R 0.8] )
T0101
G71 U1. R0.5
M1
N2
( T02 - PCLNR 2525M 12 )
( T02 - CNMG 120408 )
T0202
G71 U1. R0.5
M1
""")
        window.run()
        tagged = self.row_index(window, 'T0101')
        plain = self.row_index(window, 'T0202')
        self.assertEqual((window.table_text(tagged, 'R'), window.table_text(plain, 'R')), ('0.8', '0.8'))
        self.assertEqual(window._row_sources(tagged)['R'], spec.SOURCE_TAG)
        original = {key: window.table_text(plain, key) for key, _label in window.active_columns()}
        edited = app.LatheRow(dict(original, R='0.4'))
        edited.sources = window._row_sources(plain)
        changed = window._save_lathe_spec_edits(original, edited)
        window._propagate_lathe_specs(plain, original, edited, changed)
        self.assertEqual(window.table_text(tagged, 'R'), '0.8')            # 태그가 있는 행은 그대로
        self.assertEqual(window.lathe_store.get_insert('CNMG 120408'), {'R': '0.4'})

    def test_dialog_tooltip_warns_that_program_values_change_only_this_table(self):
        window, _directory = self.make_window()
        index = self.row_index(window, 'T0101')                            # R = 태그
        seen = {}

        def action(dialog, fields):
            seen['r'] = fields['R'].toolTip()
            seen['t'] = fields['T'].toolTip()
            self.click(dialog, standard=app.QDialogButtonBox.Cancel)

        self.drive_dialog(window, action, row_index=index)
        self.assertIn('이번 표에서만', seen['r'])
        self.assertNotIn('이번 표에서만', seen['t'])

    def test_failed_save_warning_survives_the_dialog_save_flow(self):
        """저장 흐름의 마지막 update_count()가 경고를 덮어써 사용자가 못 보던 문제."""
        window, _directory = self.make_window()
        index = self.row_index(window, 'T0505')

        def broken_save():
            raise OSError('read-only folder')

        window.lathe_store.save = broken_save

        def action(dialog, fields):
            fields['T'].setText('3')
            self.click(dialog, standard=app.QDialogButtonBox.Save)

        self.drive_dialog(window, action, row_index=index)
        self.assertIn('저장하지 못했습니다', window.count.text())
        self.assertEqual(window.table_text(index, 'T'), '3')                # 이번 표에는 반영

    def test_failed_save_is_reported_not_swallowed(self):
        window, _directory = self.make_window()
        index = self.row_index(window, 'T0505')
        original = {key: window.table_text(index, key) for key, _label in window.active_columns()}

        def broken_save():
            raise OSError('disk full')

        window.lathe_store.save = broken_save
        edited = app.LatheRow(dict(original, T='3'))
        edited.sources = window._row_sources(index)
        window._save_lathe_spec_edits(original, edited)
        self.assertIn('저장하지 못했습니다', window.count.text())
        self.assertEqual(window.lathe_store.get_insert('MY-GROOVE INSERT'), {'T': '3'})   # 이번 실행에서는 유지

    def test_edit_without_insert_is_saved_under_the_holder_name(self):
        window, _directory = self.make_window()
        window.src.setPlainText("N1\n( T07 - MGEHR 2525-3 )\nT0707\nG75 R0.5\nM1\n")
        window.run()
        index = self.row_index(window, 'T0707')
        self.assertEqual(window.table_text(index, 'INSERT'), '')

        def action(dialog, fields):
            fields['T'].setText('3')
            self.click(dialog, standard=app.QDialogButtonBox.Save)

        self.drive_dialog(window, action, row_index=index)
        self.assertEqual(window.lathe_store.get_insert('', 'MGEHR 2525-3'), {'T': '3'})
        window.run()
        self.assertEqual(window.table_text(self.row_index(window, 'T0707'), 'T'), '3')

    def test_propagation_skips_other_holders_for_kind_and_direction(self):
        window, _directory = self.make_window()
        index = self.row_index(window, 'T0303')
        other = self.row_index(window, 'T0404')
        window.table.item(other, [k for k, _l in app.LATHE_COLUMNS].index('HOLDER')).setText('PCLNL 2525M 12')
        original = {key: window.table_text(index, key) for key, _label in window.active_columns()}
        edited = app.LatheRow(dict(original, KIND='내경', R='0.4'))
        window._propagate_lathe_specs(index, original, edited, ['KIND', 'R'])
        self.assertEqual(window.table_text(other, 'R'), '0.4')             # 인서트 값은 홀더와 무관하게 전파
        self.assertEqual(window.table_text(other, 'KIND'), '외경')          # 종류는 같은 홀더+인서트만


if __name__ == '__main__':
    unittest.main()
