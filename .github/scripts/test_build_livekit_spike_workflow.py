#!/usr/bin/env python3
"""Static workflow/trust tripwire for the public LiveKit spike build workflow.

Mirrors test_build_omi_ios_workflow.py: standard library only, so the public
runner's trust boundary is protected without needing a YAML parser here.

This lane is narrower than the Omi lane on purpose. It holds no signing
secrets and emits no signed artifact, so the invariants worth defending are
(a) manual dispatch of an immutable, ancestry-checked source commit,
(b) the read-only deploy key is destroyed before any admitted source runs, and
(c) the build stays unsigned and simulator-only.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
WORKFLOW_PATH = SCRIPT_DIR.parent / "workflows" / "build-livekit-spike.yml"
CHECKOUT_SHA = "11d5960a326750d5838078e36cf38b85af677262"
UPLOAD_SHA = "ea165f8d65b6e75b540449e92b4886f43607fa02"
SOURCE_BRANCH = "feature/livekit-direct-spike"
SOURCE_REF = f"refs/remotes/origin/{SOURCE_BRANCH}"


class BuildLiveKitSpikeWorkflowTripwireTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
        cls.validate_job = cls.workflow.split("  validate-source-sha:\n", 1)[1].split(
            "  build-livekit-spike:\n", 1
        )[0]
        cls.build_job = cls.workflow.split("  build-livekit-spike:\n", 1)[1]
        cls.admission = cls.build_job.split(
            "      - name: Admit and checkout protected omp-wakeword spike source\n",
            1,
        )[1].split("      - name: Select and verify pinned Xcode\n", 1)[0]

    def test_is_manual_only_with_immutable_source_input(self) -> None:
        self.assertIn("on:\n  workflow_dispatch:\n", self.workflow)
        self.assertNotRegex(
            self.workflow, r"(?m)^  (?:push|pull_request|schedule|workflow_call):"
        )
        self.assertRegex(
            self.workflow,
            r"source_sha:\n        description: Immutable 40-hex omp-wakeword source commit SHA\n        required: true\n        type: string",
        )
        self.assertIn("permissions:\n  contents: read\n", self.workflow)
        self.assertIn("if: github.ref == 'refs/heads/main'", self.build_job)

    def test_validation_precedes_the_macos_job_and_enforces_this_contract(self) -> None:
        self.assertIn("runs-on: ubuntu-latest", self.validate_job)
        self.assertIn(
            "source_sha: ${{ steps.validate.outputs.source_sha }}", self.validate_job
        )
        self.assertIn("SOURCE_SHA: ${{ inputs.source_sha }}", self.validate_job)
        self.assertIn("^[0-9A-Fa-f]{40}$", self.validate_job)
        self.assertIn("${SOURCE_SHA,,}", self.validate_job)
        self.assertIn("uses: actions/checkout@" + CHECKOUT_SHA, self.validate_job)
        self.assertIn(
            "run: python3 .github/scripts/test_build_livekit_spike_workflow.py",
            self.validate_job,
        )
        self.assertIn("needs: validate-source-sha", self.build_job)
        self.assertIn("runs-on: macos-15", self.build_job)
        self.assertIn("environment: omp-wakeword-source-read", self.build_job)

    def test_private_source_is_branch_admitted_and_key_dies_before_execution(
        self,
    ) -> None:
        self.assertEqual(self.workflow.count("secrets.OMP_WAKEWORD_DEPLOY_KEY"), 1)
        self.assertNotIn("ssh-key:", self.workflow)
        self.assertNotIn("repository: n4s5ti/omp-wakeword", self.workflow)
        self.assertNotIn("github.token", self.workflow)
        self.assertNotIn("secrets.GITHUB_TOKEN", self.workflow)

        self.assertIn(
            "SOURCE_SHA: ${{ needs.validate-source-sha.outputs.source_sha }}",
            self.admission,
        )
        self.assertIn(
            "OMP_WAKEWORD_DEPLOY_KEY: ${{ secrets.OMP_WAKEWORD_DEPLOY_KEY }}",
            self.admission,
        )
        self.assertIn("git@github.com:n4s5ti/omp-wakeword.git", self.admission)
        self.assertIn(
            "expected_fingerprint='SHA256:+DiY3wvvV6TuJJhbpZisF/zLDA0zPMSvHdkr4UvCOqU'",
            self.admission,
        )
        # Anchored to whole lines: a commented-out `#unset ...` must not satisfy
        # a cleanup assertion.
        checkout_index = self.admission.find(
            'git checkout --quiet --detach "$SOURCE_SHA"'
        )
        self.assertNotEqual(checkout_index, -1)
        for cleanup_command in (
            "unset OMP_WAKEWORD_DEPLOY_KEY",
            "git remote remove origin",
            "unset GIT_SSH_COMMAND",
            "cleanup_source_key",
            'test ! -e "$deploy_key"',
            'test ! -e "$known_hosts"',
        ):
            match = re.search(
                r"(?m)^[ \t]*" + re.escape(cleanup_command) + r"[ \t]*$",
                self.admission,
            )
            self.assertIsNotNone(
                match, msg=f"missing cleanup command line: {cleanup_command}"
            )
            self.assertLess(match.start(), checkout_index)

        after_admission = self.build_job.split(
            "      - name: Select and verify pinned Xcode\n", 1
        )[1]
        self.assertNotIn("OMP_WAKEWORD_DEPLOY_KEY", after_admission)

    def test_ancestry_is_checked_against_the_spike_branch_not_main(self) -> None:
        self.assertIn(
            f"git fetch --quiet --no-tags origin '+refs/heads/{SOURCE_BRANCH}:{SOURCE_REF}'",
            self.admission,
        )
        self.assertIn('git cat-file -e "${SOURCE_SHA}^{commit}"', self.admission)
        self.assertIn(
            f'git merge-base --is-ancestor "$SOURCE_SHA" {SOURCE_REF}', self.admission
        )
        self.assertIn('git checkout --quiet --detach "$SOURCE_SHA"', self.admission)
        self.assertIn('test "$(git rev-parse HEAD)" = "$SOURCE_SHA"', self.admission)
        # A spike commit lives on the feature branch and is deliberately NOT on main.
        # Admitting against main would make this lane undispatchable, or worse, would
        # tempt someone to widen the fetch refspec to every branch.
        self.assertNotIn("refs/heads/main:refs/remotes/origin/main", self.admission)
        self.assertNotIn(
            'git merge-base --is-ancestor "$SOURCE_SHA" refs/remotes/origin/main',
            self.admission,
        )
        self.assertNotRegex(self.admission, r"\+refs/heads/\*")

    def test_pinned_toolchain_and_actions(self) -> None:
        self.assertIn(
            "DEVELOPER_DIR: /Applications/Xcode_16.4.app/Contents/Developer",
            self.build_job,
        )
        self.assertIn("expected=$'Xcode 16.4\\nBuild version 16F6'", self.build_job)
        self.assertIn("uses: actions/upload-artifact@" + UPLOAD_SHA, self.build_job)
        for action in re.findall(r"uses: ([^\s]+)", self.workflow):
            self.assertRegex(
                action,
                r"@[0-9a-f]{40}$",
                msg=f"third-party action is not pinned to a full SHA: {action}",
            )

    def test_build_is_unsigned_simulator_only_and_holds_no_signing_secrets(
        self,
    ) -> None:
        self.assertIn("xcodebuild build \\", self.build_job)
        self.assertIn("-project LiveKitSpike.xcodeproj", self.build_job)
        self.assertIn("-scheme LiveKitSpike", self.build_job)
        self.assertIn(
            "-destination 'generic/platform=iOS Simulator'",
            self.build_job,
        )
        self.assertIn("CODE_SIGNING_ALLOWED=NO", self.build_job)
        for forbidden in (
            "IOS_SIGNING_CERTIFICATE_BASE64",
            "IOS_SIGNING_CERTIFICATE_PASSWORD",
            "IOS_PROVISIONING_PROFILES_BASE64",
            "IPA_ARTIFACT_ENCRYPTION_CERT_PEM",
            "-allowProvisioningUpdates",
            "xcodebuild archive",
        ):
            self.assertNotIn(forbidden, self.workflow)

    def test_build_log_is_always_uploaded(self) -> None:
        upload = self.build_job.split("      - name: Upload xcodebuild log\n", 1)[1]
        self.assertIn(
            "if: always() && steps.build.outcome != 'skipped'",
            upload,
        )
        self.assertIn(
            "path: ${{ runner.temp }}/livekit-spike-build/xcodebuild.log", upload
        )
        self.assertIn("if-no-files-found: error", upload)
        # A failing compile is the point of this lane, so the log must survive it.
        build_step = self.build_job.split(
            "      - name: Build the spike for the iOS Simulator\n", 1
        )[1].split("      - name: Upload xcodebuild log\n", 1)[0]
        self.assertIn('tee "$log"', build_step)
        self.assertIn("set -o pipefail", build_step)
        self.assertIn('exit "$status"', build_step)


if __name__ == "__main__":
    unittest.main()
