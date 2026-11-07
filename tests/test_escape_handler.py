import re
from pathlib import Path
import pytest

def test_escape_handler_exits_early():
    '''
    WCAG 2.1.1 (Keyboard), 2.1.2 (No Keyboard Trap), and 2.4.3 (Focus Order)
    Tests that the Escape key handler in app.js correctly guards against closing
    multiple modals/drawers simultaneously when one is already handled.
    '''
    js_content = (Path(__file__).resolve().parents[1] / "app/static/app.js").read_text()

    escape_block = re.search(r'if \(e\.key === "Escape"\) \{(.*?)\}\n  \}\);', js_content, re.DOTALL)
    assert escape_block, "Could not find Escape handler"

    block_text = escape_block.group(1)

    assert "handled = true" in block_text, "Escape handler missing guard against fall-through"

    # ensure it closes modal only if not handled
    assert "!handled && adminDrawer" in block_text
    assert "!handled && breakdownModal" in block_text
    assert "!handled && careerDrawer" in block_text
    assert "!handled && box" in block_text

    # check priority order
    idx_clubhouse = block_text.index("clubhouseSheetModal")
    idx_breakdown = block_text.index("breakdownModal")
    idx_career = block_text.index("careerDrawer")
    idx_admin = block_text.index("adminDrawer")
    idx_caddy = block_text.index("box = document.getElementById(\"caddyModeBox\")")

    assert idx_clubhouse < idx_breakdown < idx_career < idx_admin < idx_caddy, "Escape handler is incorrectly ordered (needs to prioritize closing overlays over page-elements)"
