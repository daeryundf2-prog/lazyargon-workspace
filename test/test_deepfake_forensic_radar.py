import os
import re
import struct
import sys
import tempfile
import importlib.util
from pathlib import Path
import unittest

try:
    import pytest
except ImportError:
    class _MockPytest:
        @staticmethod
        def importorskip(modname):
            import importlib
            try:
                return importlib.import_module(modname)
            except ImportError:
                raise unittest.SkipTest(f"{modname} not installed")
    pytest = _MockPytest()

ROOT = Path(__file__).resolve().parents[1]
SKILL_ROOT = ROOT / 'skills' / 'deepfake-forensic-radar'

def load_module(name, relpath):
    path = ROOT / relpath
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(relpath)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

analyzer = load_module('analyze_deepfake_evidence', 'scripts/analyze_deepfake_evidence.py')

def test_skill_structure_and_references():
    assert (SKILL_ROOT / 'SKILL.md').exists()
    ref_dir = SKILL_ROOT / 'references'
    assert ref_dir.exists()
    
    expected_refs = [
        '01_generation_synthesis.md',
        '02_detection_forensics.md',
        '03_c2pa_watermarks.md',
        '04_legal_and_court.md',
        '05_evasion_and_limits.md'
    ]
    for ref in expected_refs:
        ref_path = ref_dir / ref
        assert ref_path.exists(), f'Missing reference: {ref}'
        with open(ref_path, 'r', encoding='utf-8') as f:
            content = f.read()
            assert len(content) > 100

def test_calculate_hashes():
    with tempfile.NamedTemporaryFile('wb', delete=False) as f:
        f.write(b'Deepfake Forensic Evidence Sample Test Data 2026')
        temp_path = f.name
        
    try:
        hashes = analyzer.calculate_hashes(temp_path)
        assert 'sha256' in hashes
        assert 'sha1' in hashes
        assert 'md5' in hashes
        assert hashes['size_bytes'] == 48
        assert len(hashes['sha256']) == 64
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)

def test_c2pa_scanner_and_signatures():
    with tempfile.NamedTemporaryFile('wb', delete=False) as f:
        f.write(b'header_data_sample_c2pa.actions_test_c2pa.hash.data_trailer')
        temp_path = f.name
        
    try:
        res = analyzer.scan_c2pa_jumbf(temp_path)
        assert res['c2pa_detected'] is True
        assert res['manifest_type'] == 'Raw_Manifest_Signature'
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)

def test_forensic_report_generation():
    with tempfile.NamedTemporaryFile('wb', delete=False) as f:
        f.write(b'sample image binary dummy')
        temp_path = f.name

    try:
        report = analyzer.generate_forensic_report(temp_path)
        assert 'meta' in report
        assert 'integrity_hashes' in report
        assert 'c2pa_provenance' in report
        assert 'spectral_analysis' in report

        md = analyzer.format_markdown_report(report)
        assert '# 디지털 미디어 딥페이크 포렌식 감정 보고서' in md
        assert 'SHA-256' in md
        assert '형사소송법' in md
        # 과단정 문구 금지: 해시 일치가 채택을 보장한다는 표현이 없어야 한다
        assert '증거능력이 인정됩니다' not in md
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)

# ---------------------------------------------------------------------------
# 컨테이너별 C2PA 감지 (JPEG APP11 / MP4 ISOBMFF) — SKILL.md가 보장하는 기능
# ---------------------------------------------------------------------------

def test_jpeg_app11_c2pa_detection():
    payload = b'jumb' + b'c2pa.actions' + b'\x00' * 16
    marker_len = len(payload) + 2
    data = b'\xff\xd8' + b'\xff\xeb' + struct.pack('>H', marker_len) + payload + b'tail'
    with tempfile.NamedTemporaryFile('wb', delete=False) as f:
        f.write(data)
        temp_path = f.name
    try:
        res = analyzer.scan_c2pa_jumbf(temp_path)
        assert res['c2pa_detected'] is True
        assert res['manifest_type'] == 'JPEG_APP11_JUMBF'
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)

def test_mp4_isobmff_c2pa_box_detection():
    data = (b'\x00\x00\x00\x1cftypisom\x00\x00\x02\x00isomiso2avc1mp4a'
            + b'\x00\x00\x00\x20' + b'c2pa' + b'jumb manifest payload here')
    with tempfile.NamedTemporaryFile('wb', delete=False) as f:
        f.write(data)
        temp_path = f.name
    try:
        res = analyzer.scan_c2pa_jumbf(temp_path)
        assert res['c2pa_detected'] is True
        assert res['manifest_type'] == 'ISOBMFF_c2pa_box'
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)

def test_c2pa_absent_is_reported_clean():
    with tempfile.NamedTemporaryFile('wb', delete=False) as f:
        f.write(os.urandom(4096))
        temp_path = f.name
    try:
        res = analyzer.scan_c2pa_jumbf(temp_path)
        assert res['c2pa_detected'] is False
        assert res['manifest_type'] is None
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)

# ---------------------------------------------------------------------------
# 문서-구현 드리프트 가드: SKILL.md의 실행 레시피에 등장하는 모든 CLI 플래그가
# 스크립트에 실제로 등록되어 있어야 한다 (--plot-fft 미구현 사례의 재발 방지)
# ---------------------------------------------------------------------------

def test_skill_documented_cli_flags_exist_in_script():
    skill_text = (SKILL_ROOT / 'SKILL.md').read_text(encoding='utf-8')
    script_text = (ROOT / 'scripts' / 'analyze_deepfake_evidence.py').read_text(encoding='utf-8')

    documented = set(re.findall(r'--([a-z][a-z0-9-]+)', skill_text))
    registered = set(re.findall(r'add_argument\(\s*"(--[a-z0-9-]+)"', script_text))
    registered_names = {flag.lstrip('-') for flag in registered}

    assert documented, 'SKILL.md에 CLI 플래그 문서가 없다'
    for flag in documented:
        assert flag in registered_names, f'SKILL.md 문서화 플래그 --{flag} 이(가) 스크립트에 없다'

# ---------------------------------------------------------------------------
# 레퍼런스 스트리핑 가드: 생성 파이프라인 사고로 인라인 코드/링크 텍스트가
# 통째로 삭제된 흔적(빈 불릿 `-  : `, 빈 링크 `[](`)이 남으면 실패한다
# ---------------------------------------------------------------------------

def test_references_have_no_stripped_content():
    ref_dir = SKILL_ROOT / 'references'
    empty_bullet = re.compile(r'^-\s{2,}:', re.MULTILINE)
    empty_link = re.compile(r'\[\]\(')
    for ref in sorted(ref_dir.glob('*.md')):
        content = ref.read_text(encoding='utf-8')
        assert not empty_bullet.search(content), f'{ref.name}: 빈 불릿(스트리핑 흔적) 발견'
        assert not empty_link.search(content), f'{ref.name}: 빈 링크 텍스트 [](...) 발견'

def test_references_cover_previously_missing_items():
    """전수 감사에서 누락됐던 항목들이 실제로 수록되어 있는지 고정."""
    expectations = {
        '01_generation_synthesis.md': [
            'Sora', 'Vidu', 'SimSwap', 'XTTS', 'StyleTTS2', 'Mini-Omni',
            'VoiceCraft', 'V-Express', 'MimicMotion', 'AnimateAnyone',
            'kijai/ComfyUI-WanVideoWrapper', 'kijai/ComfyUI-SUPIR',
            'inswapper_128.onnx',
        ],
        '02_detection_forensics.md': [
            'FreqNet', 'LGrad', 'RECCE', 'SBI', 'VIGIL', 'CNNDetection',
            'DFDC', 'GenImage', 'WildDeepfake', 'MMTD-Set',
        ],
        '03_c2pa_watermarks.md': ['c2pa.actions', 'c2pa.hash.data', 'c2pa-rs'],
        '04_legal_and_court.md': ['ECFS'],
        '05_evasion_and_limits.md': ['Telegram'],
    }
    ref_dir = SKILL_ROOT / 'references'
    for filename, keywords in expectations.items():
        content = (ref_dir / filename).read_text(encoding='utf-8')
        for kw in keywords:
            assert kw in content, f'{filename}에 "{kw}" 누락'

# ---------------------------------------------------------------------------
# 통합 무결성: 라우팅 문서에 스킬이 등록되어 있어야 호스트가 라우팅한다
# ---------------------------------------------------------------------------

def test_gemini_md_routes_the_skill():
    gemini = (ROOT / 'GEMINI.md').read_text(encoding='utf-8')
    assert 'skills/deepfake-forensic-radar/SKILL.md' in gemini

def test_readmd_documents_the_analyzer():
    readme = (ROOT / 'README.md').read_text(encoding='utf-8')
    assert 'analyze_deepfake_evidence.py' in readme

# ---------------------------------------------------------------------------
# --plot-fft 실동작 (matplotlib 필요)
# ---------------------------------------------------------------------------

def test_plot_fft_writes_png(tmp_path=None):
    pytest.importorskip('matplotlib')
    pytest.importorskip('PIL')
    import numpy as np
    from PIL import Image

    if tmp_path is None:
        with tempfile.TemporaryDirectory() as tmp:
            _run_fft_test(Path(tmp))
    else:
        _run_fft_test(tmp_path)

def _run_fft_test(tmp_path):
    import numpy as np
    from PIL import Image
    src = tmp_path / 'evidence.png'
    Image.fromarray((np.random.rand(128, 128) * 255).astype('uint8')).save(src)
    out = tmp_path / 'fft.png'
    rc = analyzer.plot_fft_spectrum(str(src), str(out))
    assert rc is True
    assert out.exists() and out.stat().st_size > 0


class TestDeepfakeForensicRadar(unittest.TestCase):
    def test_skill_structure_and_references(self):
        test_skill_structure_and_references()

    def test_calculate_hashes(self):
        test_calculate_hashes()

    def test_c2pa_scanner_and_signatures(self):
        test_c2pa_scanner_and_signatures()

    def test_forensic_report_generation(self):
        test_forensic_report_generation()

    def test_jpeg_app11_c2pa_detection(self):
        test_jpeg_app11_c2pa_detection()

    def test_mp4_isobmff_c2pa_box_detection(self):
        test_mp4_isobmff_c2pa_box_detection()

    def test_c2pa_absent_is_reported_clean(self):
        test_c2pa_absent_is_reported_clean()

    def test_skill_documented_cli_flags_exist_in_script(self):
        test_skill_documented_cli_flags_exist_in_script()

    def test_references_have_no_stripped_content(self):
        test_references_have_no_stripped_content()

    def test_references_cover_previously_missing_items(self):
        test_references_cover_previously_missing_items()

    def test_gemini_md_routes_the_skill(self):
        test_gemini_md_routes_the_skill()

    def test_readmd_documents_the_analyzer(self):
        test_readmd_documents_the_analyzer()

    def test_plot_fft_writes_png(self):
        test_plot_fft_writes_png()


if __name__ == '__main__':
    unittest.main()
