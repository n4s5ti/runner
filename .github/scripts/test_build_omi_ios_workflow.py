#!/usr/bin/env python3
"""Static workflow/trust tripwire for the public Omi iOS build workflow.

This deliberately uses only the standard library: it protects the public-runner
trust boundary without requiring a YAML parser in the runner repository.
"""

from __future__ import annotations

import hashlib
import re
import subprocess
import tarfile
import tempfile
import unittest
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
WORKFLOW_PATH = SCRIPT_DIR.parent / "workflows" / "build-omi-ios.yml"
DECRYPT_PATH = SCRIPT_DIR / "decrypt-omi-ios-artifact.sh"
CHECKOUT_SHA = "11d5960a326750d5838078e36cf38b85af677262"
FLUTTER_SHA = "1a449444c387b1966244ae4d4f8c696479add0b2"
RUBY_SHA = "95ef2b042f9d7a56d8268cba8559e2842e2ad01b"
UPLOAD_SHA = "ea165f8d65b6e75b540449e92b4886f43607fa02"
SIGNING_SECRETS = (
    "IOS_SIGNING_CERTIFICATE_BASE64",
    "IOS_SIGNING_CERTIFICATE_PASSWORD",
    "IOS_PROVISIONING_PROFILES_BASE64",
    "IPA_ARTIFACT_ENCRYPTION_CERT_PEM",
)


class BuildOmiIosWorkflowTripwireTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
        cls.verify_job = cls.workflow.split("  verify-ios:\n", 1)[1].split(
            "  signed-ios:\n", 1
        )[0]
        cls.signed_job = cls.workflow.split("  signed-ios:\n", 1)[1].split(
            "  unsigned-ipa:\n", 1
        )[0]
        cls.unsigned_job = cls.workflow.split("  unsigned-ipa:\n", 1)[1]

    def test_is_manual_only_with_immutable_source_input(self) -> None:
        self.assertIn("on:\n  workflow_dispatch:\n", self.workflow)
        self.assertNotRegex(
            self.workflow, r"(?m)^  (?:push|pull_request|schedule|workflow_call):"
        )
        self.assertRegex(
            self.workflow,
            r"source_sha:\n        description: Immutable 40-hex Omi source commit SHA\n        required: true\n        type: string",
        )
        self.assertRegex(
            self.workflow,
            r"mode:\n        description: Build mode\n        required: true\n        default: verify\n        type: choice\n        options:\n          - verify\n          - unsigned\n          - signed",
        )
        self.assertIn(
            "if: github.ref == 'refs/heads/main' && inputs.mode == 'verify'",
            self.verify_job,
        )
        self.assertIn(
            "if: github.ref == 'refs/heads/main' && inputs.mode == 'signed'",
            self.signed_job,
        )
        self.assertIn(
            "if: github.ref == 'refs/heads/main' && inputs.mode == 'unsigned'",
            self.unsigned_job,
        )

    def test_validation_precedes_macos_jobs_and_enforces_the_workflow_contract(
        self,
    ) -> None:
        validation = self.workflow.split("  validate-source-sha:\n", 1)[1].split(
            "  verify-ios:\n", 1
        )[0]
        self.assertIn("runs-on: ubuntu-latest", validation)
        self.assertIn(
            "source_sha: ${{ steps.validate.outputs.source_sha }}", validation
        )
        self.assertIn("SOURCE_SHA: ${{ inputs.source_sha }}", validation)
        self.assertIn("^ [0-9A-Fa-f]{40}$".replace("^ ", "^"), validation)
        self.assertIn("${SOURCE_SHA,,}", validation)
        self.assertIn("uses: actions/checkout@" + CHECKOUT_SHA, validation)
        self.assertIn(
            "run: python3 .github/scripts/test_build_omi_ios_workflow.py", validation
        )
        for job in (self.verify_job, self.signed_job, self.unsigned_job):
            self.assertIn("needs: validate-source-sha", job)
            self.assertIn("runs-on: macos-15", job)

    def test_private_source_is_main_admitted_and_key_is_destroyed_before_execution(
        self,
    ) -> None:
        self.assertEqual(self.workflow.count("secrets.OMI_SOURCE_DEPLOY_KEY"), 3)
        self.assertNotIn("ssh-key:", self.workflow)
        self.assertNotIn("repository: n4s5ti/0mi", self.workflow)
        for job in (self.verify_job, self.signed_job, self.unsigned_job):
            admission = job.split(
                "      - name: Admit and checkout protected Omi main source\n",
                1,
            )[1].split("      - name: Select and verify pinned Xcode\n", 1)[0]
            self.assertIn(
                "SOURCE_SHA: ${{ needs.validate-source-sha.outputs.source_sha }}",
                admission,
            )
            self.assertIn(
                "OMI_SOURCE_DEPLOY_KEY: ${{ secrets.OMI_SOURCE_DEPLOY_KEY }}", admission
            )
            self.assertIn("git@github.com:n4s5ti/0mi.git", admission)
            self.assertIn(
                "expected_fingerprint='SHA256:+DiY3wvvV6TuJJhbpZisF/zLDA0zPMSvHdkr4UvCOqU'",
                admission,
            )
            self.assertIn(
                "git fetch --quiet --no-tags origin '+refs/heads/main:refs/remotes/origin/main'",
                admission,
            )
            self.assertIn('git cat-file -e "${SOURCE_SHA}^{commit}"', admission)
            self.assertIn(
                'git merge-base --is-ancestor "$SOURCE_SHA" refs/remotes/origin/main',
                admission,
            )
            self.assertIn('git checkout --quiet --detach "$SOURCE_SHA"', admission)
            self.assertIn('test "$(git rev-parse HEAD)" = "$SOURCE_SHA"', admission)
            self.assertIn("git remote remove origin", admission)
            self.assertIn("unset OMI_SOURCE_DEPLOY_KEY", admission)
            self.assertIn("unset GIT_SSH_COMMAND", admission)
            self.assertIn('test ! -e "$deploy_key"', admission)
            self.assertIn('test ! -e "$known_hosts"', admission)
            checkout_index = admission.find(
                'git checkout --quiet --detach "$SOURCE_SHA"'
            )
            for cleanup_command in (
                "git remote remove origin",
                "unset GIT_SSH_COMMAND",
                "          cleanup_source_key\n",
                'test ! -e "$deploy_key"',
                'test ! -e "$known_hosts"',
            ):
                cleanup_index = admission.find(cleanup_command)
                self.assertNotEqual(cleanup_index, -1)
                self.assertLess(cleanup_index, checkout_index)
            after_admission = job.split(
                "      - name: Select and verify pinned Xcode\n", 1
            )[1]
            self.assertNotIn("OMI_SOURCE_DEPLOY_KEY", after_admission)
        self.assertNotIn("github.token", self.workflow)
        self.assertNotIn("secrets.GITHUB_TOKEN", self.workflow)

    def test_both_modes_require_protected_main_ancestry_before_source_execution(
        self,
    ) -> None:
        for job in (self.verify_job, self.signed_job, self.unsigned_job):
            admission = job.split(
                "      - name: Admit and checkout protected Omi main source\n",
                1,
            )[1].split("      - name: Select and verify pinned Xcode\n", 1)[0]
            self.assertIn(
                "SOURCE_SHA: ${{ needs.validate-source-sha.outputs.source_sha }}",
                admission,
            )
            self.assertIn('git cat-file -e "${SOURCE_SHA}^{commit}"', admission)
            self.assertIn(
                'git merge-base --is-ancestor "$SOURCE_SHA" refs/remotes/origin/main',
                admission,
            )
            self.assertIn('git checkout --quiet --detach "$SOURCE_SHA"', admission)
            self.assertIn('test "$(git rev-parse HEAD)" = "$SOURCE_SHA"', admission)

    def test_every_action_is_pinned_to_the_omi_full_sha(self) -> None:
        expected_actions = {
            "actions/checkout": CHECKOUT_SHA,
            "subosito/flutter-action": FLUTTER_SHA,
            "ruby/setup-ruby": RUBY_SHA,
            "actions/upload-artifact": UPLOAD_SHA,
        }
        uses = re.findall(r"(?m)^        uses: ([^@\s]+)@([^\s#]+)", self.workflow)
        self.assertEqual(dict(uses), expected_actions)
        self.assertEqual(len(uses), 9)
        for action, revision in uses:
            self.assertRegex(revision, r"^[0-9a-f]{40}$")
            self.assertEqual(revision, expected_actions[action])

    def test_signing_is_environment_gated_and_artifacts_are_encrypted(self) -> None:
        self.assertIn("environment: omi-ios-signing", self.signed_job)
        self.assertIn("environment: omi-ios-source-read", self.verify_job)
        unsigned_path = self.workflow.split("  signed-ios:\n", 1)[0]
        for secret in SIGNING_SECRETS:
            self.assertNotIn(secret, unsigned_path)
            self.assertIn(f"{secret}: ${{{{ secrets.{secret} }}}}", self.signed_job)
        for signing_only_secret in SIGNING_SECRETS[:3]:
            self.assertNotIn(signing_only_secret, self.unsigned_job)
        self.assertIn("- name: Validate protected signing secrets", self.signed_job)
        self.assertIn("- name: Build, sign, and verify dev IPA", self.signed_job)
        self.assertIn(
            "run: bash .github/scripts/build-signed-ios-dev-ipa.sh", self.signed_job
        )
        self.assertIn(
            "OMI_SOURCE_SHA: ${{ needs.validate-source-sha.outputs.source_sha }}",
            self.signed_job,
        )
        self.assertIn(
            "- name: Encrypt signed IPA artifact and publish-safe summary",
            self.signed_job,
        )
        self.assertIn(
            "openssl cms -encrypt -binary -aes-256-cbc -outform DER",
            self.signed_job,
        )
        self.assertIn(
            'tar -C "$RUNNER_TEMP/ios-dev-ipa" -czf "$archive" omi-dev.ipa receipt.txt',
            self.signed_job,
        )
        self.assertIn('rm -rf "$RUNNER_TEMP/ios-dev-ipa"', self.signed_job)
        self.assertIn(
            "printf 'source_sha=%s\\nciphertext_sha256=%s\\n'",
            self.signed_job,
        )
        encryption = self.signed_job.split(
            "      - name: Encrypt signed IPA artifact and publish-safe summary\n",
            1,
        )[1].split(
            "      - name: Upload encrypted signed IPA artifact and public summary\n",
            1,
        )[
            0
        ]
        self.assertIn(
            "IPA_ARTIFACT_ENCRYPTION_CERT_PEM: ${{ secrets.IPA_ARTIFACT_ENCRYPTION_CERT_PEM }}",
            encryption,
        )

        upload = self.signed_job.split(
            "      - name: Upload encrypted signed IPA artifact and public summary\n",
            1,
        )[1]
        self.assertIn("uses: actions/upload-artifact@" + UPLOAD_SHA, upload)
        self.assertIn("omi-ios-artifact.tar.gz.cms", upload)
        self.assertIn("public-summary.txt", upload)
        for forbidden in (".ipa", "receipt.txt", ".mobileprovision", ".tar.gz\n"):
            self.assertNotIn(forbidden, upload)
        self.assertNotIn("actions/upload-artifact", self.verify_job)

    def test_unsigned_job_builds_without_signing_and_publishes_only_ciphertext(
        self,
    ) -> None:
        self.assertIn("environment: omi-ios-source-read", self.unsigned_job)
        self.assertIn(
            "flutter build ios --release --flavor dev --no-codesign",
            self.unsigned_job,
        )
        self.assertIn(
            "- name: Package unsigned dev IPA and receipt", self.unsigned_job
        )
        self.assertIn(
            'tar -C "$RUNNER_TEMP/ios-dev-ipa" -czf "$archive" omi-dev.ipa receipt.txt',
            self.unsigned_job,
        )
        self.assertIn(
            "openssl cms -encrypt -binary -aes-256-cbc -outform DER",
            self.unsigned_job,
        )
        self.assertIn(
            "IPA_ARTIFACT_ENCRYPTION_CERT_PEM: ${{ secrets.IPA_ARTIFACT_ENCRYPTION_CERT_PEM }}",
            self.unsigned_job,
        )
        self.assertIn('rm -rf "$RUNNER_TEMP/ios-dev-ipa"', self.unsigned_job)
        upload = self.unsigned_job.split(
            "      - name: Upload encrypted unsigned IPA artifact and public summary\n",
            1,
        )[1]
        self.assertIn("uses: actions/upload-artifact@" + UPLOAD_SHA, upload)
        self.assertIn("omi-ios-artifact.tar.gz.cms", upload)
        self.assertIn("public-summary.txt", upload)
        for forbidden in (".ipa\n", "receipt.txt", ".mobileprovision", ".tar.gz\n"):
            self.assertNotIn(forbidden, upload)

    def test_frozen_toolchain_and_jags_parity_are_asserted_in_both_macos_jobs(
        self,
    ) -> None:
        for job in (self.verify_job, self.signed_job, self.unsigned_job):
            for required in (
                "DEVELOPER_DIR: /Applications/Xcode_16.4.app/Contents/Developer",
                "expected=$'Xcode 16.4\\nBuild version 16F6'",
                "Require committed frozen Swift package resolution",
                "Package.resolved",
                "uses: subosito/flutter-action@" + FLUTTER_SHA,
                "flutter-version: 3.41.9",
                "cache: false",
                "uses: ruby/setup-ruby@" + RUBY_SHA,
                "ruby-version: 3.3.12",
                "bundler: 4.0.3",
                'test "$("$ruby_bin/bundle" --version)" = \'4.0.3\'',
                "flutter pub get --enforce-lockfile",
                "bundle config set --local deployment true",
                'test "$("$RUNNER_TEMP/bundle-bin/pod" --version)" = \'1.16.2\'',
                'pod" install --deployment',
                "-scheme JagsParityTests",
                "-disableAutomaticPackageResolution",
            ):
                self.assertIn(required, job)


class EncryptedArtifactContractTests(unittest.TestCase):
    def test_encrypted_artifact_round_trip_and_receipt_checksum(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            private_key = root / "recipient-key.pem"
            recipient_cert = root / "recipient-cert.pem"
            ipa = root / "omi-dev.ipa"
            receipt = root / "receipt.txt"
            archive = root / "artifact.tar.gz"
            ciphertext = root / "artifact.tar.gz.cms"
            output_dir = root / "decrypted"
            ipa.write_bytes(b"test signed IPA payload")
            receipt.write_text(
                f"artifact=omi-dev.ipa\nsha256={hashlib.sha256(ipa.read_bytes()).hexdigest()}\n",
                encoding="utf-8",
            )
            subprocess.run(
                [
                    "openssl",
                    "req",
                    "-x509",
                    "-newkey",
                    "rsa:2048",
                    "-nodes",
                    "-keyout",
                    str(private_key),
                    "-out",
                    str(recipient_cert),
                    "-subj",
                    "/CN=Omi IPA artifact test",
                    "-days",
                    "1",
                ],
                check=True,
                capture_output=True,
            )
            with tarfile.open(archive, "w:gz") as tar:
                tar.add(ipa, arcname="omi-dev.ipa")
                tar.add(receipt, arcname="receipt.txt")
            subprocess.run(
                [
                    "openssl",
                    "cms",
                    "-encrypt",
                    "-binary",
                    "-aes-256-cbc",
                    "-outform",
                    "DER",
                    "-in",
                    str(archive),
                    "-out",
                    str(ciphertext),
                    str(recipient_cert),
                ],
                check=True,
                capture_output=True,
            )

            subprocess.run(
                [
                    str(DECRYPT_PATH),
                    str(ciphertext),
                    str(recipient_cert),
                    str(private_key),
                    str(output_dir),
                ],
                check=True,
                capture_output=True,
                text=True,
            )

            self.assertEqual(
                (output_dir / "omi-dev.ipa").read_bytes(), ipa.read_bytes()
            )
            self.assertEqual(
                (output_dir / "receipt.txt").read_text(encoding="utf-8"),
                receipt.read_text(encoding="utf-8"),
            )


if __name__ == "__main__":
    unittest.main()
