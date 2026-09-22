"""Local installation check; no browser automation, account access, or uploads."""
from pathlib import Path
import importlib.util
import json
import os
import sys
import tempfile

from PIL import Image, ImageDraw, ImageFont

XHS = Path(__file__).resolve().parent
os.environ['PLAYWRIGHT_BROWSERS_PATH'] = str(XHS / '.browsers')
SUPERVISOR = Path('/Users/hadley/.local/share/Supervisor-Skills')
SKILLS = Path('/Users/hadley/.codex/skills')
sys.path.insert(0, str(XHS))
from main import run_existing_images_flow
from playwright.sync_api import sync_playwright

spec = importlib.util.spec_from_file_location('supervisor_lint', SUPERVISOR / 'scripts/lint_skills.py')
linter = importlib.util.module_from_spec(spec)
spec.loader.exec_module(linter)
skill_errors = []
names = []
for source in sorted((SUPERVISOR / 'skills').iterdir()):
    if not (source / 'SKILL.md').exists():
        continue
    names.append(source.name)
    destination = SKILLS / source.name
    skill_errors.extend(linter.lint_skill(destination))
    for file in source.rglob('*'):
        if file.is_file():
            installed = destination / file.relative_to(source)
            if not installed.exists() or installed.read_bytes() != file.read_bytes():
                skill_errors.append(f'Installation mismatch: {installed}')

sample = Path(tempfile.mkdtemp(prefix='xhs-ocr-install-test-', dir='/private/tmp'))
inputs = sample / 'images'
inputs.mkdir()
im = Image.new('RGB', (1500, 470), 'white')
draw = ImageDraw.Draw(im)
font = ImageFont.truetype('/System/Library/Fonts/Supplemental/Arial.ttf', 64)
draw.text((50, 55), 'Research notes OCR test 12345', font=font, fill='black')
draw.text((50, 175), 'Save Markdown locally', font=font, fill='black')
chinese_font = ImageFont.truetype('/System/Library/Fonts/STHeiti Medium.ttc', 64)
draw.text((50, 295), '科研笔记文字提取测试', font=chinese_font, fill='black')
im.save(inputs / 'OCR测试_1_安装检查_来自小红书网页版.png')
ok = run_existing_images_flow(inputs, sample / 'notes', str(sample / 'output.txt'))
output = (sample / 'output.txt').read_text()
assert ok and '12345' in output and 'Markdown' in output and '科研' in output, output
assert list((sample / 'notes').glob('*.md'))
with sync_playwright() as pw:
    browser_binary = pw.chromium.executable_path
    assert Path(browser_binary).exists(), browser_binary
report = {
    'supervisor_commit': '207bc6f7a1aa107e544099c2c7cc86816fba9628',
    'installed_skill_count': len(names), 'skills': names,
    'skill_structural_or_copy_errors': skill_errors,
    'xhs_commit': '3c7e814565158e0389fbebdaa72081c6c1622e5a',
    'ocr_to_markdown_local_smoke': 'PASS',
    'sample_directory': str(sample), 'recognized_text': output,
    'browser_binary_installed': browser_binary,
    'live_xhs_link_test': 'NOT_RUN: no user link supplied; no account login',
}
(XHS / 'relocation-check.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
print(json.dumps(report, ensure_ascii=False, indent=2))
assert not skill_errors, skill_errors
