from pathlib import Path
from html.parser import HTMLParser

class AccessibleDialogParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.dialogs = []

    def handle_starttag(self, tag, attrs):
        attrs_dict = dict(attrs)
        if attrs_dict.get('role') == 'dialog':
            self.dialogs.append(attrs_dict)

def test_static_html_dialogs_have_aria_modal():
    """
    Ensures that all statically defined dialogs in index.html have aria-modal="true"
    and an aria-labelledby attribute for screen readers.
    """
    html_content = (Path(__file__).resolve().parents[1] / "app/static/index.html").read_text(encoding='utf-8')
    parser = AccessibleDialogParser()
    parser.feed(html_content)

    # Ensure we actually found some dialogs to test against regressions
    assert len(parser.dialogs) >= 3, "Expected at least 3 modal dialogs in index.html"

    for dialog_attrs in parser.dialogs:
        assert dialog_attrs.get('aria-modal') == 'true', f"Dialog missing aria-modal='true': {dialog_attrs}"
        assert 'aria-labelledby' in dialog_attrs, f"Dialog missing aria-labelledby: {dialog_attrs}"

        # Verify the labeled ID exists in the document
        label_id = dialog_attrs.get('aria-labelledby')
        # Check both single and double quotes
        assert f'id="{label_id}"' in html_content or f"id='{label_id}'" in html_content, f"Label ID '{label_id}' not found in document"

class StatusParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.status_nodes = []

    def handle_starttag(self, tag, attrs):
        attrs_dict = dict(attrs)
        if attrs_dict.get('role') == 'status':
            self.status_nodes.append(attrs_dict)

def test_static_html_toast_aria_live():
    """
    Ensures that the toast element uses polite aria-live to announce status messages.
    """
    html_content = (Path(__file__).resolve().parents[1] / "app/static/index.html").read_text(encoding='utf-8')
    parser = StatusParser()
    parser.feed(html_content)

    assert len(parser.status_nodes) > 0, "No status nodes found"
    toast_node = next((node for node in parser.status_nodes if node.get('id') == 'toast'), None)

    assert toast_node is not None, "Toast node missing role='status'"
    assert toast_node.get('aria-live') == 'polite', "Toast node missing aria-live='polite'"
    assert toast_node.get('aria-atomic') == 'true', "Toast node missing aria-atomic='true'"
