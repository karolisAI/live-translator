import io
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from live_translator.errors import AssetIntegrityError
from live_translator.validate_assets import PACKAGED_COMPONENTS, main


class ValidateAssetsCommandTests(unittest.TestCase):
    def test_default_validates_exactly_the_packaged_components(self) -> None:
        with (
            patch("live_translator.validate_assets.load_manifest", return_value=object()),
            patch(
                "live_translator.validate_assets.verify_manifest",
                return_value={"a": Path("a")},
            ) as verify,
            redirect_stdout(io.StringIO()) as output,
        ):
            result = main(["--root", ".", "--manifest", "manifest.json"])

        self.assertEqual(result, 0)
        self.assertEqual(verify.call_args.kwargs["components"], PACKAGED_COMPONENTS)
        self.assertIn("1 files", output.getvalue())

    def test_validation_failure_returns_nonzero_and_reports_reason(self) -> None:
        with (
            patch("live_translator.validate_assets.load_manifest", return_value=object()),
            patch(
                "live_translator.validate_assets.verify_manifest",
                side_effect=AssetIntegrityError("modified piper.exe"),
            ),
            redirect_stderr(io.StringIO()) as error,
        ):
            result = main(["--root", ".", "--manifest", "manifest.json"])

        self.assertEqual(result, 1)
        self.assertIn("modified piper.exe", error.getvalue())

    def test_explicit_components_replace_packaged_defaults(self) -> None:
        with (
            patch("live_translator.validate_assets.load_manifest", return_value=object()),
            patch("live_translator.validate_assets.verify_manifest", return_value={}) as verify,
            redirect_stdout(io.StringIO()),
        ):
            result = main(
                [
                    "--root",
                    ".",
                    "--manifest",
                    "manifest.json",
                    "--component",
                    "parakeet-model",
                ]
            )

        self.assertEqual(result, 0)
        self.assertEqual(verify.call_args.kwargs["components"], ("parakeet-model",))


if __name__ == "__main__":
    unittest.main()
