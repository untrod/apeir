/**
 * Versioned desktop UI-state migration.
 *
 * Runtime, workspace, provider, conversation, task, and artifact data are not
 * owned by this module and are never deleted here. Session credentials are
 * deliberately invalidated and reloaded from the trusted Tauri bridge.
 */

export const UI_STATE_SCHEMA_VERSION = 2;
const SCHEMA_KEY = "nous_ui_schema_version";
const MIGRATION_REPORT_KEY = "nous_migration_report";
const UI_BACKUP_KEY = "nous_ui_state_backup";

const LEGACY_KEYS = [
  "nous_onboarding_completed",
  "nous_setup_complete",
  "nous_provider_id",
  "nous_workspace_path",
  "nous_language",
  "nous_developer_mode",
  "nous_server_url",
  "nous_server_token",
];

const RESETTABLE_UI_KEYS = [
  SCHEMA_KEY,
  MIGRATION_REPORT_KEY,
  "nous_onboarding_completed",
  "nous_setup_complete",
  "nous_developer_mode",
];

export interface MigrationReport {
  fromVersion: number;
  toVersion: number;
  migrated: string[];
  preserved: string[];
  reset: string[];
  errors: string[];
}

function readSchemaVersion(): number {
  const value = Number.parseInt(localStorage.getItem(SCHEMA_KEY) || "0", 10);
  return Number.isFinite(value) && value >= 0 ? value : 0;
}

export function migrateOldState(): MigrationReport {
  const fromVersion = readSchemaVersion();
  const report: MigrationReport = {
    fromVersion,
    toVersion: UI_STATE_SCHEMA_VERSION,
    migrated: [],
    preserved: [],
    reset: [],
    errors: [],
  };

  for (const key of LEGACY_KEYS) {
    try {
      const value = localStorage.getItem(key);
      if (value === null) continue;
      if (key === "nous_server_token") {
        localStorage.removeItem(key);
        report.reset.push(key);
      } else {
        // These values are user preferences or references. Preserve them until
        // a future schema has an explicit replacement field.
        report.preserved.push(key);
      }
    } catch (error) {
      report.errors.push(`${key}: ${error instanceof Error ? error.message : String(error)}`);
    }
  }

  try {
    sessionStorage.removeItem("nous_server_token");
    report.reset.push("session:nous_server_token");
  } catch (error) {
    report.errors.push(`session: ${error instanceof Error ? error.message : String(error)}`);
  }

  try {
    localStorage.setItem(SCHEMA_KEY, String(UI_STATE_SCHEMA_VERSION));
    if (fromVersion !== UI_STATE_SCHEMA_VERSION) report.migrated.push(SCHEMA_KEY);
  } catch (error) {
    report.errors.push(`schema: ${error instanceof Error ? error.message : String(error)}`);
  }

  return report;
}

export function saveMigrationReport(report: MigrationReport): void {
  try {
    localStorage.setItem(
      MIGRATION_REPORT_KEY,
      JSON.stringify({ ...report, timestamp: new Date().toISOString() }),
    );
  } catch {
    // Diagnostics must never prevent application startup.
  }
}

/** Reset only disposable desktop UI state and preserve all Runtime-owned data. */
export function resetUIState(): void {
  const backup: Record<string, string> = {};
  for (const key of RESETTABLE_UI_KEYS) {
    try {
      const value = localStorage.getItem(key);
      if (value !== null) backup[key] = value;
    } catch {
      // Continue with the remaining keys.
    }
  }

  try {
    localStorage.setItem(
      UI_BACKUP_KEY,
      JSON.stringify({ schemaVersion: UI_STATE_SCHEMA_VERSION, createdAt: new Date().toISOString(), values: backup }),
    );
  } catch {
    // A failed backup should not broaden the deletion scope.
  }

  for (const key of RESETTABLE_UI_KEYS) {
    try {
      localStorage.removeItem(key);
    } catch {
      // Continue with the remaining keys.
    }
  }

  try {
    sessionStorage.removeItem("nous_server_url");
    sessionStorage.removeItem("nous_server_token");
  } catch {
    // The next bootstrap will establish a fresh local session.
  }
}