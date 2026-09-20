"""PySide6 pages for the unified model installer."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from PySide6.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWizard,
    QWizardPage,
)

from nous_runtime.model_distribution.catalog import (
    Ed25519CatalogVerifier,
    ModelCatalog,
)
from nous_runtime.model_distribution.installer import (
    InstallerStep,
    ModelInstallerController,
)
from nous_runtime.model_runtime.errors import ModelResolutionError


def _message_page(title: str, text: str) -> QWizardPage:
    page = QWizardPage()
    page.setTitle(title)
    layout = QVBoxLayout(page)
    label = QLabel(text)
    label.setWordWrap(True)
    layout.addWidget(label)
    layout.addStretch(1)
    return page


def create_installer_wizard(
    controller: ModelInstallerController,
) -> QWizard:
    """Build the 11-page installer on top of one shared controller."""
    wizard = QWizard()
    wizard.setWindowTitle("Nous Unified Model Runtime Setup")
    wizard.setMinimumSize(760, 520)
    context: dict[str, Any] = {"catalog": None}

    welcome = _message_page(
        "Welcome",
        "Configure replaceable local and remote model backends. Nous keeps "
        "installation, enablement, loading, routing, and task ownership "
        "separate.",
    )

    environment = QWizardPage()
    environment.setTitle("Environment")
    environment_layout = QVBoxLayout(environment)
    hardware = controller.inspect_environment()
    hardware_text = QTextEdit()
    hardware_text.setReadOnly(True)
    hardware_text.setPlainText(
        json.dumps(
            {
                "disk_mb": hardware.disk_mb,
                "memory_mb": hardware.memory_mb,
                "vram_mb": hardware.vram_mb,
                "gpu_packages": hardware.allow_gpu_packages,
            },
            indent=2,
        )
    )
    environment_layout.addWidget(
        QLabel("Detected capacity used by the package resolver:")
    )
    environment_layout.addWidget(hardware_text)

    location = QWizardPage()
    location.setTitle("Install location")
    location_layout = QFormLayout(location)
    root_value = QLineEdit(str(controller.install_root))
    root_value.setReadOnly(True)
    location_layout.addRow("Nous workspace", root_value)
    location_layout.addRow(
        QLabel("Use --path when launching to choose another workspace.")
    )

    capabilities = QWizardPage()
    capabilities.setTitle("Capabilities")
    capabilities_layout = QVBoxLayout(capabilities)
    capability_boxes: dict[str, QCheckBox] = {}
    for capability in (
        "reasoning",
        "coding",
        "vision",
        "audio",
        "embedding",
        "rerank",
    ):
        box = QCheckBox(capability)
        box.setChecked(capability == "reasoning")
        capability_boxes[capability] = box
        capabilities_layout.addWidget(box)
    capabilities_layout.addStretch(1)

    plan = QWizardPage()
    plan.setTitle("Model plan")
    plan_layout = QVBoxLayout(plan)
    catalog_row = QHBoxLayout()
    catalog_path = QLineEdit()
    catalog_browse = QPushButton("Browse catalog")
    catalog_row.addWidget(catalog_path)
    catalog_row.addWidget(catalog_browse)
    allow_unsigned = QCheckBox(
        "Allow unsigned trusted local catalog (development only)"
    )
    plan_button = QPushButton("Generate minimal plan")
    plan_output = QTextEdit()
    plan_output.setReadOnly(True)
    plan_layout.addLayout(catalog_row)
    plan_layout.addWidget(allow_unsigned)
    plan_layout.addWidget(plan_button)
    plan_layout.addWidget(plan_output)

    def browse_catalog() -> None:
        selected, _ = QFileDialog.getOpenFileName(
            wizard,
            "Select model catalog",
            str(controller.install_root),
            "JSON files (*.json)",
        )
        if selected:
            catalog_path.setText(selected)

    def generate_plan() -> None:
        try:
            selected_capabilities = [
                name
                for name, box in capability_boxes.items()
                if box.isChecked()
            ]
            modalities = ["text"]
            modality_map = {
                "vision": "image",
                "audio": "audio",
                "embedding": "embedding",
                "rerank": "rerank",
            }
            modalities.extend(
                modality
                for capability, modality in modality_map.items()
                if capability in selected_capabilities
            )
            controller.select_capabilities(
                selected_capabilities,
                modalities,
            )
            public_key = os.environ.get(
                "NOUS_MODEL_CATALOG_PUBLIC_KEY",
                "",
            )
            verifier = (
                Ed25519CatalogVerifier(public_key)
                if public_key
                else None
            )
            catalog = ModelCatalog.load(
                catalog_path.text(),
                verifier=verifier,
                require_signature=not allow_unsigned.isChecked(),
            )
            context["catalog"] = catalog
            controller.state.catalog_path = catalog_path.text()
            resolution = controller.plan(catalog, hardware=hardware)
            plan_output.setPlainText(
                json.dumps(
                    {
                        "complete": resolution.complete,
                        "packages": [
                            item.package_id
                            for item in resolution.selected_packages
                        ],
                        "disk_mb": resolution.estimated_disk_mb,
                        "vram_mb": resolution.estimated_vram_mb,
                        "warnings": list(resolution.warnings),
                    },
                    indent=2,
                )
            )
            if not resolution.complete:
                raise ModelResolutionError(
                    "catalog cannot cover all selected capabilities"
                )
        except Exception as exc:
            QMessageBox.critical(wizard, "Planning failed", str(exc))

    catalog_browse.clicked.connect(browse_catalog)
    plan_button.clicked.connect(generate_plan)

    licenses = QWizardPage()
    licenses.setTitle("Licenses")
    licenses_layout = QVBoxLayout(licenses)
    license_acceptance = QCheckBox(
        "I reviewed and accept the selected package licenses."
    )
    licenses_layout.addWidget(
        QLabel(
            "Unapproved packages are excluded by default. Acceptance remains "
            "explicit before any download."
        )
    )
    licenses_layout.addWidget(license_acceptance)
    licenses_layout.addStretch(1)

    download = QWizardPage()
    download.setTitle("Download")
    download_layout = QVBoxLayout(download)
    download_button = QPushButton("Download and verify selected artifacts")
    download_output = QTextEdit()
    download_output.setReadOnly(True)
    download_layout.addWidget(download_button)
    download_layout.addWidget(download_output)

    def download_models() -> None:
        try:
            catalog = context.get("catalog")
            if catalog is None:
                raise ModelResolutionError("generate a model plan first")
            if not license_acceptance.isChecked():
                raise ModelResolutionError(
                    "accept selected licenses before download"
                )
            controller.accept_licenses(
                list(controller.state.selected_packages)
            )
            paths = controller.download_selected(catalog)
            download_output.setPlainText(
                json.dumps(paths, indent=2)
                if paths
                else "No downloadable artifacts were required."
            )
        except Exception as exc:
            QMessageBox.critical(wizard, "Download failed", str(exc))

    download_button.clicked.connect(download_models)

    imported = QWizardPage()
    imported.setTitle("Import local model")
    imported_layout = QVBoxLayout(imported)
    import_row = QHBoxLayout()
    import_path = QLineEdit()
    import_browse = QPushButton("Browse model")
    import_row.addWidget(import_path)
    import_row.addWidget(import_browse)
    import_button = QPushButton("Import by reference")
    import_status = QLabel("Optional")
    imported_layout.addLayout(import_row)
    imported_layout.addWidget(import_button)
    imported_layout.addWidget(import_status)
    imported_layout.addStretch(1)

    def browse_import() -> None:
        selected, _ = QFileDialog.getOpenFileName(
            wizard,
            "Select local model",
            str(Path.home()),
            "Model files (*.gguf *.safetensors *.onnx);;All files (*)",
        )
        if selected:
            import_path.setText(selected)

    def import_model() -> None:
        try:
            if not import_path.text().strip():
                raise ModelResolutionError("select a model file first")
            model_id = controller.import_local(import_path.text())
            import_status.setText(f"Registered {model_id}")
        except Exception as exc:
            QMessageBox.critical(wizard, "Import failed", str(exc))

    import_browse.clicked.connect(browse_import)
    import_button.clicked.connect(import_model)

    providers = QWizardPage()
    providers.setTitle("Cloud and remote Providers")
    providers_layout = QFormLayout(providers)
    provider_id = QLineEdit()
    credential_ref = QLineEdit()
    provider_save = QPushButton("Save credential reference")
    provider_status = QLabel("Optional")
    providers_layout.addRow("Provider ID", provider_id)
    providers_layout.addRow("Credential reference", credential_ref)
    providers_layout.addRow(provider_save)
    providers_layout.addRow(provider_status)

    def save_provider() -> None:
        try:
            controller.set_provider_reference(
                provider_id.text(),
                credential_ref.text(),
            )
            provider_status.setText("Reference saved; no secret stored.")
        except Exception as exc:
            QMessageBox.critical(
                wizard,
                "Provider reference failed",
                str(exc),
            )

    provider_save.clicked.connect(save_provider)

    class VerificationPage(QWizardPage):
        def validatePage(self) -> bool:
            return verify_installation()

    verification = VerificationPage()
    verification.setTitle("Verification")
    verification_layout = QVBoxLayout(verification)
    verify_button = QPushButton("Verify installation")
    verify_output = QTextEdit()
    verify_output.setReadOnly(True)
    verification_layout.addWidget(verify_button)
    verification_layout.addWidget(verify_output)

    def verify_installation() -> bool:
        try:
            result = controller.verify()
        except Exception as exc:
            QMessageBox.critical(
                wizard,
                "Verification failed",
                str(exc),
            )
            return False
        verify_output.setPlainText(json.dumps(result, indent=2))
        verified = bool(result["ok"])
        if not verified:
            QMessageBox.warning(
                wizard,
                "Verification incomplete",
                "\n".join(result["errors"]),
            )
        return verified

    verify_button.clicked.connect(verify_installation)

    complete = _message_page(
        "Complete",
        "The unified model runtime is prepared. Models stay unloaded until a "
        "task requests their capabilities.",
    )

    for page in (
        welcome,
        environment,
        location,
        capabilities,
        plan,
        licenses,
        download,
        imported,
        providers,
        verification,
        complete,
    ):
        wizard.addPage(page)

    def track_step(page_id: int) -> None:
        try:
            controller.advance(InstallerStep(page_id))
        except ModelResolutionError as exc:
            QMessageBox.warning(wizard, "Installer state", str(exc))

    wizard.currentIdChanged.connect(track_step)
    return wizard


__all__ = ["create_installer_wizard"]
