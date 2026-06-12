"use client";

import { Suspense, useCallback, useEffect, useMemo, useState } from "react";
import AppHeader from "@/components/layout/AppHeader";
import { api, ApiError, apiUploadWithProgress } from "@/lib/api-client";
import { useArangoConnectionStatus } from "@/lib/useArangoConnectionStatus";

type Environment = "aws" | "gcs" | "local";

interface ConnectionProfile {
  profile_key: string;
  display_name: string;
  environment: Environment;
  cluster_name: string;
  username: string;
  password: string;
  password_set: boolean;
  server_endpoint: string;
  protocol: string;
  port: number;
  kubeconfig_stored: boolean;
  kubeconfig_filename: string;
  saved: boolean;
}

interface ProfileTemplate {
  environment: Environment;
  display_name: string;
  cluster_name: string;
  server_endpoint: string;
  protocol: string;
  port: number;
}

interface ProfilesResponse {
  active_profile: string;
  profile_keys: string[];
  profiles: Record<string, ConnectionProfile>;
  templates: Record<Environment, ProfileTemplate>;
}

const ENV_OPTIONS: { value: Environment; label: string; hint: string }[] = [
  {
    value: "aws",
    label: "AWS",
    hint: "EKS / managed Arango endpoint in AWS",
  },
  {
    value: "gcs",
    label: "GCS",
    hint: "GKE / managed Arango endpoint on Google Cloud",
  },
  {
    value: "local",
    label: "Local",
    hint: "Minikube on your laptop (tunnel host or localhost port-forward)",
  },
];

const PASSWORD_UNCHANGED = "__UNCHANGED__";
const NEW_DRAFT_KEY = "__new__";
const MINIKUBE_INSTALLER_URL =
  "https://github.com/gblock-arango/single-node-arango-on-minikube";

function templateToForm(template: ProfileTemplate): {
  display_name: string;
  environment: Environment;
  username: string;
  password: string;
  server_endpoint: string;
  cluster_name: string;
} {
  return {
    display_name: template.display_name,
    environment: template.environment,
    username: "root",
    password: "",
    server_endpoint: template.server_endpoint || "",
    cluster_name: template.cluster_name || "",
  };
}

export default function ConnectionPage() {
  return (
    <Suspense
      fallback={
        <main className="min-h-screen bg-gray-50 flex items-center justify-center text-gray-500">
          Loading…
        </main>
      }
    >
      <ConnectionPageInner />
    </Suspense>
  );
}

function ConnectionPageInner() {
  const { refresh } = useArangoConnectionStatus();
  const [profiles, setProfiles] = useState<Record<string, ConnectionProfile>>({});
  const [draftProfiles, setDraftProfiles] = useState<Record<string, ConnectionProfile>>({});
  const [profileKeys, setProfileKeys] = useState<string[]>([]);
  const [templates, setTemplates] = useState<Record<Environment, ProfileTemplate> | null>(
    null,
  );
  const [activeProfile, setActiveProfile] = useState("");
  const [selectedKey, setSelectedKey] = useState<string>(NEW_DRAFT_KEY);
  const [form, setForm] = useState({
    display_name: "AWS",
    environment: "aws" as Environment,
    username: "root",
    password: "",
    server_endpoint: "",
    cluster_name: "aws-arango",
  });
  const [passwordDirty, setPasswordDirty] = useState(false);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [connecting, setConnecting] = useState(false);
  const [uploadingKube, setUploadingKube] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [testResult, setTestResult] = useState<string | null>(null);

  const allProfiles = useMemo(
    () => ({ ...draftProfiles, ...profiles }),
    [draftProfiles, profiles],
  );

  const applyProfileToForm = useCallback((profile: ConnectionProfile) => {
    setForm({
      display_name: profile.display_name || profile.profile_key,
      environment: profile.environment || "aws",
      username: profile.username || "root",
      password: "",
      server_endpoint: profile.server_endpoint || "",
      cluster_name: profile.cluster_name || "",
    });
    setPasswordDirty(false);
    setTestResult(null);
    setMessage(null);
  }, []);

  const startNewDraft = useCallback(
    (environment: Environment = "aws") => {
      const template = templates?.[environment];
      if (template) {
        setForm(templateToForm(template));
      } else {
        setForm({
          display_name: environment === "local" ? "Local" : environment === "gcs" ? "GCS" : "AWS",
          environment,
          username: "root",
          password: "",
          server_endpoint: environment === "local" ? "127.0.0.1" : "",
          cluster_name:
            environment === "local"
              ? "local-minikube-dev"
              : environment === "gcs"
                ? "gcs-arango"
                : "aws-arango",
        });
      }
      setSelectedKey(NEW_DRAFT_KEY);
      setPasswordDirty(false);
      setTestResult(null);
      setMessage(null);
      setError(null);
    },
    [templates],
  );

  const loadProfiles = useCallback(
    async (preserveKey?: string) => {
      setLoading(true);
      setError(null);
      try {
        const data = await api.get<ProfilesResponse>("/api/v1/connection/profiles");
        setProfiles(data.profiles);
        setProfileKeys(data.profile_keys || Object.keys(data.profiles));
        setTemplates(data.templates);
        setActiveProfile(data.active_profile || "");

        const keys = data.profile_keys?.length
          ? data.profile_keys
          : Object.keys(data.profiles);

        if (preserveKey && preserveKey !== NEW_DRAFT_KEY && data.profiles[preserveKey]) {
          setSelectedKey(preserveKey);
          applyProfileToForm(data.profiles[preserveKey]);
          return;
        }

        const initialKey =
          (data.active_profile && data.profiles[data.active_profile]
            ? data.active_profile
            : keys[0]) || NEW_DRAFT_KEY;

        setSelectedKey(initialKey);
        if (initialKey === NEW_DRAFT_KEY) {
          startNewDraft("aws");
        } else if (data.profiles[initialKey]) {
          applyProfileToForm(data.profiles[initialKey]);
        }
      } catch (err) {
        setError(
          err instanceof ApiError
            ? err.body.message
            : "Failed to load connection profiles.",
        );
      } finally {
        setLoading(false);
      }
    },
    [applyProfileToForm, startNewDraft],
  );

  useEffect(() => {
    void loadProfiles();
    // eslint-disable-next-line react-hooks/exhaustive-deps -- initial load only
  }, []);

  useEffect(() => {
    if (templates && selectedKey === NEW_DRAFT_KEY && !form.display_name) {
      startNewDraft(form.environment);
    }
  }, [templates, selectedKey, form.display_name, form.environment, startNewDraft]);

  const currentProfile =
    selectedKey && selectedKey !== NEW_DRAFT_KEY ? allProfiles[selectedKey] : undefined;
  const envHint = ENV_OPTIONS.find((e) => e.value === form.environment)?.hint;
  const isNewDraft = selectedKey === NEW_DRAFT_KEY;

  const buildSavePayload = () => ({
    display_name: form.display_name.trim() || "Connection",
    environment: form.environment,
    username: form.username.trim() || "root",
    password: passwordDirty ? form.password : PASSWORD_UNCHANGED,
    server_endpoint: form.server_endpoint.trim(),
    cluster_name: form.cluster_name.trim(),
  });

  const ensureProfileKey = async (): Promise<string> => {
    if (!isNewDraft && selectedKey) {
      return selectedKey;
    }
    const res = await api.post<{ profile_key: string; profile: ConnectionProfile }>(
      "/api/v1/connection/profiles",
      {
        display_name: form.display_name.trim() || templates?.[form.environment]?.display_name,
        environment: form.environment,
      },
    );
    setDraftProfiles((prev) => ({ ...prev, [res.profile_key]: res.profile }));
    setSelectedKey(res.profile_key);
    return res.profile_key;
  };

  const handleSelectProfile = (key: string) => {
    if (key === NEW_DRAFT_KEY) {
      startNewDraft(form.environment);
      return;
    }
    setSelectedKey(key);
    const profile = allProfiles[key];
    if (profile) {
      applyProfileToForm(profile);
    }
  };

  const handleSave = async () => {
    setSaving(true);
    setError(null);
    setMessage(null);
    try {
      const key = await ensureProfileKey();
      const res = await api.put<{ profile: ConnectionProfile }>(
        `/api/v1/connection/profiles/${key}`,
        buildSavePayload(),
      );
      setProfiles((prev) => ({ ...prev, [key]: res.profile }));
      setDraftProfiles((prev) => {
        const next = { ...prev };
        delete next[key];
        return next;
      });
      if (res.profile.saved && !profileKeys.includes(key)) {
        setProfileKeys((prev) => [...prev, key]);
      }
      setPasswordDirty(false);
      setForm((f) => ({ ...f, password: "" }));
      setMessage("Saved to UC volume.");
      refresh({ force: true });
    } catch (err) {
      setError(err instanceof ApiError ? err.body.message : "Save failed.");
    } finally {
      setSaving(false);
    }
  };

  const handleTest = async () => {
    setTesting(true);
    setError(null);
    setTestResult(null);
    try {
      const key = await ensureProfileKey();
      const res = await api.post<{
        ok: boolean;
        probe?: { latency_ms?: number; error?: string; response_preview?: string };
      }>(`/api/v1/connection/profiles/${key}/test`, buildSavePayload());
      if (res.ok) {
        const ms = res.probe?.latency_ms;
        setTestResult(
          ms != null ? `Connection OK (${ms}ms)` : "Connection OK",
        );
      } else {
        setTestResult(
          res.probe?.error || "Connection test failed — check endpoint and credentials.",
        );
      }
    } catch (err) {
      setError(err instanceof ApiError ? err.body.message : "Test failed.");
    } finally {
      setTesting(false);
    }
  };

  const handleConnect = async () => {
    setConnecting(true);
    setError(null);
    setMessage(null);
    try {
      const key = await ensureProfileKey();
      await api.put(`/api/v1/connection/profiles/${key}`, buildSavePayload());
      const res = await api.post<{
        active_profile_display_name?: string;
        registry?: { cluster_name?: string };
      }>(`/api/v1/connection/profiles/${key}/activate`, {});
      setActiveProfile(key);
      const label =
        res.active_profile_display_name ||
        res.registry?.cluster_name ||
        allProfiles[key]?.display_name ||
        key;
      setMessage(`Connected using ${label}. Gateway path verified.`);
      refresh({ force: true });
      await loadProfiles(key);
    } catch (err) {
      setError(err instanceof ApiError ? err.body.message : "Connect failed.");
      refresh({ force: true });
    } finally {
      setConnecting(false);
    }
  };

  const handleKubeconfigUpload = async (file: File | null) => {
    if (!file) return;
    setUploadingKube(true);
    setError(null);
    setMessage(null);
    try {
      const key = await ensureProfileKey();
      const formData = new FormData();
      formData.append("file", file);
      const res = await apiUploadWithProgress(
        `/api/v1/connection/profiles/${key}/kubeconfig`,
        formData,
      );
      if (!res.ok) {
        throw new Error(await res.text());
      }
      setMessage(`KubeConfig stored: ${file.name}`);
      await loadProfiles(key);
    } catch (err) {
      setError(err instanceof Error ? err.message : "KubeConfig upload failed.");
    } finally {
      setUploadingKube(false);
    }
  };

  const savedConnectionOptions = useMemo(
    () =>
      profileKeys.map((key) => ({
        key,
        label: profiles[key]?.display_name || key,
        isActive: activeProfile === key,
      })),
    [profileKeys, profiles, activeProfile],
  );

  const selectorOptions = useMemo(() => {
    const drafts = Object.keys(draftProfiles)
      .filter((key) => !profileKeys.includes(key))
      .map((key) => ({
        key,
        label: `${draftProfiles[key]?.display_name || key} (unsaved)`,
        isActive: false,
      }));
    return [
      { key: NEW_DRAFT_KEY, label: "New connection…", isActive: false },
      ...savedConnectionOptions,
      ...drafts,
    ];
  }, [profileKeys, draftProfiles, savedConnectionOptions]);

  const topSelectorValue = profileKeys.includes(selectedKey) ? selectedKey : "";

  return (
    <main className="min-h-screen bg-gray-50">
      <AppHeader
        title="Arango Connection"
        subtitle="Configure username, password, server endpoint, and optional KubeConfig. Save to UC, then Connect to activate for arango-gateway-app."
      />

      <div className="max-w-3xl mx-auto px-6 py-8 space-y-6">
        {loading ? (
          <p className="text-sm text-gray-500 animate-pulse">Loading profiles…</p>
        ) : (
          <>
            <section className="bg-white rounded-xl border border-gray-200 shadow-sm p-4">
              <label className="block">
                <span className="text-sm font-medium text-gray-700">Saved connections</span>
                <select
                  value={topSelectorValue}
                  onChange={(e) => handleSelectProfile(e.target.value)}
                  disabled={savedConnectionOptions.length === 0}
                  className="mt-1 w-full rounded-lg border border-gray-300 px-3 py-2 text-sm text-gray-900 shadow-sm focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500 disabled:bg-gray-50 disabled:text-gray-500"
                >
                  {savedConnectionOptions.length === 0 ? (
                    <option value="">No saved connections yet</option>
                  ) : (
                    <>
                      <option value="" disabled>
                        Select a saved connection…
                      </option>
                      {savedConnectionOptions.map((opt) => (
                        <option key={opt.key} value={opt.key}>
                          {opt.label}
                          {opt.isActive ? " (active)" : ""}
                        </option>
                      ))}
                    </>
                  )}
                </select>
              </label>
              {activeProfile && profiles[activeProfile] ? (
                <p className="mt-2 text-xs text-gray-500">
                  Active:{" "}
                  <span className="font-medium text-emerald-700">
                    {profiles[activeProfile].display_name || activeProfile}
                  </span>
                </p>
              ) : null}
            </section>

            <p className="text-sm text-gray-600 bg-slate-50 border border-slate-200 rounded-lg px-4 py-3">
              <strong>Save</strong> stores credentials on the UC workflow volume (
              <code className="text-xs">arango_workflow_volume/workflow-data/settings/</code>
              ). <strong>Connect</strong> writes the active endpoint to{" "}
              <code className="text-xs">workspace.default.arango_connection_registry</code>{" "}
              (used by arango-gateway-app). Add/fill fields below, then Save → Connect.
            </p>

            {(error || message) && (
              <div className="space-y-2">
                {error ? (
                  <p className="text-sm text-red-700 bg-red-50 border border-red-100 rounded-lg px-3 py-2">
                    {error}
                  </p>
                ) : null}
                {message ? (
                  <p className="text-sm text-emerald-700 bg-emerald-50 border border-emerald-100 rounded-lg px-3 py-2">
                    {message}
                  </p>
                ) : null}
              </div>
            )}

          <section className="bg-white rounded-xl border border-gray-200 shadow-sm p-6 space-y-5">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <h2 className="text-sm font-semibold text-gray-900">Connection details</h2>
              {!isNewDraft && activeProfile === selectedKey ? (
                <span className="text-xs font-medium uppercase tracking-wide text-emerald-700">
                  Active
                </span>
              ) : null}
            </div>

            <label className="block">
              <span className="text-sm font-medium text-gray-700">Connection</span>
              <select
                value={selectedKey}
                onChange={(e) => handleSelectProfile(e.target.value)}
                className="mt-1 w-full rounded-lg border border-gray-300 px-3 py-2 text-sm text-gray-900 shadow-sm focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500"
              >
                {selectorOptions.map((opt) => (
                  <option key={opt.key} value={opt.key}>
                    {opt.label}
                    {opt.isActive ? " (active)" : ""}
                  </option>
                ))}
              </select>
              {profileKeys.length === 0 && isNewDraft ? (
                <p className="mt-2 text-sm text-yellow-700 italic">
                  Fill in the fields below, then Save with endpoint and password.
                </p>
              ) : null}
            </label>

            {envHint ? <p className="text-sm text-gray-500">{envHint}</p> : null}

            {form.environment === "local" ? (
              <a
                href={MINIKUBE_INSTALLER_URL}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center rounded-lg border border-indigo-200 bg-indigo-50 px-4 py-2 text-sm font-medium text-indigo-800 hover:bg-indigo-100 hover:border-indigo-300 transition-colors"
              >
                Download Minikube Arango Installer for Local Deploys
              </a>
            ) : null}

            <div className="grid gap-4 sm:grid-cols-2">
              <Field label="Display name">
                <input
                  type="text"
                  value={form.display_name}
                  onChange={(e) => setForm((f) => ({ ...f, display_name: e.target.value }))}
                  placeholder="AWS Production"
                  className={inputClass}
                />
              </Field>
              <Field label="Environment">
                <select
                  value={form.environment}
                  onChange={(e) => {
                    const env = e.target.value as Environment;
                    if (isNewDraft && templates?.[env]) {
                      setForm(templateToForm(templates[env]));
                    } else {
                      setForm((f) => ({ ...f, environment: env }));
                    }
                  }}
                  className={inputClass}
                >
                  {ENV_OPTIONS.map((opt) => (
                    <option key={opt.value} value={opt.value}>
                      {opt.label}
                    </option>
                  ))}
                </select>
              </Field>
              <Field label="Username">
                <input
                  type="text"
                  value={form.username}
                  onChange={(e) => setForm((f) => ({ ...f, username: e.target.value }))}
                  className={inputClass}
                  autoComplete="username"
                />
              </Field>
              <Field label="Password">
                <input
                  type="password"
                  value={form.password}
                  placeholder={
                    currentProfile?.password_set
                      ? "•••••••• (saved on UC volume)"
                      : "Enter password"
                  }
                  onChange={(e) => {
                    setPasswordDirty(true);
                    setForm((f) => ({ ...f, password: e.target.value }));
                  }}
                  className={inputClass}
                  autoComplete="current-password"
                />
              </Field>
            </div>

            <Field label="Server endpoint">
              <input
                type="text"
                value={form.server_endpoint}
                onChange={(e) =>
                  setForm((f) => ({ ...f, server_endpoint: e.target.value }))
                }
                placeholder="gg8dcifd.rnd.pilot.arango.ai"
                className={inputClass}
              />
              <p className="mt-1 text-xs text-gray-500">
                Hostname or full URL. HTTPS on port 443 is assumed when omitted.
              </p>
            </Field>

            <Field label="Cluster name">
              <input
                type="text"
                value={form.cluster_name}
                onChange={(e) =>
                  setForm((f) => ({ ...f, cluster_name: e.target.value }))
                }
                className={inputClass}
              />
            </Field>

            <Field label="KubeConfig">
              <div className="flex flex-wrap items-center gap-3">
                <label className="inline-flex items-center gap-2 rounded-lg border border-gray-200 bg-gray-50 px-3 py-2 text-sm text-gray-700 hover:bg-gray-100 cursor-pointer">
                  <input
                    type="file"
                    accept=".yaml,.yml,.conf"
                    className="sr-only"
                    disabled={uploadingKube}
                    onChange={(e) => {
                      const file = e.target.files?.[0] ?? null;
                      void handleKubeconfigUpload(file);
                      e.target.value = "";
                    }}
                  />
                  {uploadingKube ? "Uploading…" : "Load file"}
                </label>
                {currentProfile?.kubeconfig_stored ? (
                  <span className="text-xs text-emerald-700">
                    Cached: {currentProfile.kubeconfig_filename || "kubeconfig.yaml"}
                  </span>
                ) : (
                  <span className="text-xs text-gray-500">
                    Optional — stored under workflow-data/settings/kubeconfig/
                  </span>
                )}
              </div>
            </Field>

            {testResult ? (
              <p
                className={`text-sm rounded-lg px-3 py-2 border ${
                  testResult.startsWith("Connection OK")
                    ? "text-emerald-700 bg-emerald-50 border-emerald-100"
                    : "text-amber-800 bg-amber-50 border-amber-100"
                }`}
              >
                {testResult}
              </p>
            ) : null}

            <div className="flex flex-wrap gap-3 pt-2">
              <ActionButton onClick={() => void handleSave()} disabled={saving}>
                {saving ? "Saving…" : "Save"}
              </ActionButton>
              <ActionButton
                onClick={() => void handleTest()}
                disabled={testing}
                variant="secondary"
              >
                {testing ? "Testing…" : "Test connection"}
              </ActionButton>
              <ActionButton onClick={() => void handleConnect()} disabled={connecting}>
                {connecting ? "Connecting…" : "Connect"}
              </ActionButton>
            </div>
          </section>
          </>
        )}
      </div>
    </main>
  );
}

function Field({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <label className="block">
      <span className="text-sm font-medium text-gray-700">{label}</span>
      <div className="mt-1">{children}</div>
    </label>
  );
}

const inputClass =
  "w-full rounded-lg border border-gray-300 px-3 py-2 text-sm text-gray-900 shadow-sm focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500";

function ActionButton({
  children,
  onClick,
  disabled,
  variant = "primary",
}: {
  children: React.ReactNode;
  onClick: () => void;
  disabled?: boolean;
  variant?: "primary" | "secondary";
}) {
  const className =
    variant === "secondary"
      ? "inline-flex items-center rounded-lg border border-gray-300 bg-white px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50 disabled:opacity-50"
      : "inline-flex items-center rounded-lg border border-indigo-600 bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-700 disabled:opacity-50";
  return (
    <button type="button" onClick={onClick} disabled={disabled} className={className}>
      {children}
    </button>
  );
}
