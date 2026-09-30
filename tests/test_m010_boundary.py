"""M010: the foundation package must be as structurally bounded as the view.

The Observatory's existing source guard proves the renderer cannot write. M010
adds the same kind of proof for the foundation package, which is on the opposite
side of the boundary: it may execute a binary, so what it must not do is
create a subject, perform a birth, or reach for the network.

The scan is an import walk, not a text scan. A module that documents "this never
imports subject" would pass a text scan, so the text scan would prove nothing.
"""
import ast
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
FOUNDATION_DIR = REPO_ROOT / "foundation"

#: Packages the foundation layer must never import, and why.
FORBIDDEN_IMPORTS = {
    "subject": "M010 must not create a subject",
    "birth": "M010 must not perform birth or reach the ceremony",
    "control": "M010 must not drive the control protocol",
    "observatory": "the Observatory is a view and must not be a dependency of the model layer",
    "observer": "the observer is a read-only human view, not a foundation dependency",
    "provenance": "the foundation layer records its own ledger; it does not write the human one",
}

#: Network-capable modules, none of which may appear on a local-only path.
NETWORK_MODULES = {
    "socket", "ssl", "urllib", "http", "requests", "httpx", "aiohttp",
    "ftplib", "smtplib", "telnetlib", "xmlrpc", "asyncio",
}

#: Model-acquisition libraries. Their presence would mean the laboratory could
#: obtain a model, which the milestone forbids outright.
ACQUISITION_MODULES = {
    "huggingface_hub", "transformers", "safetensors", "accelerate", "peft",
    "trl", "datasets", "gdown", "boto3", "ray", "modelscope", "timm",
}

#: Learning and memory libraries. The inference test is stateless and the
#: artifact must not change, so none of these may appear.
LEARNING_MODULES = {
    "torch", "tensorflow", "jax", "numpy", "faiss", "chromadb", "chroma",
    "pinecone", "weaviate", "qdrant_client", "langchain", "llama_index",
    "sentence_transformers", "scipy", "sklearn",
}


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                found.add(node.module)
            # A relative import names its own package, so resolve it.
            if node.level and node.module:
                found.add(node.module)
    return found


class FoundationBoundaryTests(unittest.TestCase):
    def test_package_is_not_empty(self) -> None:
        self.assertTrue(FOUNDATION_DIR.is_dir(), "foundation package is missing")
        self.assertTrue(list(FOUNDATION_DIR.glob("*.py")))

    def test_no_forbidden_package_imports(self) -> None:
        for path in sorted(FOUNDATION_DIR.glob("*.py")):
            for imported in _imports(path):
                head = imported.split(".")[0]
                self.assertNotIn(
                    head, FORBIDDEN_IMPORTS,
                    f"{path.name} imports {imported}: "
                    f"{FORBIDDEN_IMPORTS.get(head, '')}",
                )

    def test_no_network_imports(self) -> None:
        for path in sorted(FOUNDATION_DIR.glob("*.py")):
            for imported in _imports(path):
                self.assertNotIn(
                    imported.split(".")[0], NETWORK_MODULES,
                    f"{path.name} imports {imported}; M010 is local-only",
                )

    def test_no_acquisition_imports(self) -> None:
        for path in sorted(FOUNDATION_DIR.glob("*.py")):
            for imported in _imports(path):
                self.assertNotIn(
                    imported.split(".")[0], ACQUISITION_MODULES,
                    f"{path.name} imports {imported}; the laboratory never acquires",
                )

    def test_no_learning_or_memory_imports(self) -> None:
        for path in sorted(FOUNDATION_DIR.glob("*.py")):
            for imported in _imports(path):
                self.assertNotIn(
                    imported.split(".")[0], LEARNING_MODULES,
                    f"{path.name} imports {imported}; no learning, no memory",
                )

    def test_subprocess_is_always_bounded(self) -> None:
        """Any subprocess use must be an argument vector with shell=False."""
        for path in sorted(FOUNDATION_DIR.glob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                dotted = ast.unparse(node.func)
                if dotted not in {"subprocess.run", "subprocess.Popen"}:
                    continue
                keywords = {k.arg: k for k in node.keywords or []}
                if dotted == "subprocess.run":
                    self.assertIn(
                        "shell", keywords,
                        f"{path.name} calls subprocess.run without an explicit "
                        "shell=False",
                    )
                    self.assertEqual(
                        "False", ast.unparse(keywords["shell"].value).strip()
                    )
                self.assertNotIn(
                    "start_new_session", keywords,
                    f"{path.name} starts a detached session",
                )
                self.assertNotIn("preexec_fn", keywords)

    def test_subprocess_calls_pass_a_timeout(self) -> None:
        """A runtime invocation must be bounded in time as well as in privilege.

        The bound may arrive positionally or as a keyword; what must not happen
        is an invocation that waits forever. An unbounded probe against a
        misbehaving binary would hang the laboratory rather than report a
        failure.
        """
        for path in sorted(FOUNDATION_DIR.glob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                if ast.unparse(node.func) != "subprocess.run":
                    continue
                keywords = {k.arg for k in node.keywords or []}
                has_keyword_timeout = "timeout" in keywords
                # subprocess.run(cmd, bufsize=..., ...) places bufsize positionally.
                has_positional_timeout = len(node.args) > 1
                self.assertTrue(
                    has_keyword_timeout or has_positional_timeout,
                    f"{path.name} calls subprocess.run with no timeout, so a "
                    "misbehaving binary would hang the laboratory",
                )

    def test_subprocess_stdin_is_closed(self) -> None:
        """No runtime may inherit a console, or it could be prompted."""
        for path in sorted(FOUNDATION_DIR.glob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                if ast.unparse(node.func) != "subprocess.run":
                    continue
                keywords = {k.arg for k in node.keywords or []}
                self.assertIn(
                    "stdin", keywords,
                    f"{path.name} leaves stdin attached to the parent's console",
                )

    def test_observatory_does_not_import_a_probe(self) -> None:
        """The view must not be able to trigger the execution it reports on.

        ``foundation_status`` takes ``with_runtime_probe`` precisely so the
        Observatory can leave it off. If the session ever passed True, polling
        the display would execute a binary, so the call site is pinned.
        """
        terminal = (REPO_ROOT / "observatory" / "terminal.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("with_runtime_probe=False", terminal)
        self.assertNotIn("with_runtime_probe=True", terminal)

    def test_validation_summary_denies_subject_and_birth(self) -> None:
        """The ledger's own summary is the last line of defence on this claim."""
        from foundation.validation import validate

        ledger = validate(REPO_ROOT)
        summary = ledger.to_dict()["summary"]
        self.assertIs(summary["birth_performed"], False)
        self.assertIs(summary["subject_created"], False)


if __name__ == "__main__":
    unittest.main(verbosity=2)
