import {
  staticClasses,
  PanelSection,
  PanelSectionRow,
  ButtonItem,
  DialogButton,
  ConfirmModal,
  showModal,
} from "@decky/ui";
import { callable, definePlugin, FileSelectionType, openFilePicker } from "@decky/api";
import { Fragment, useState, useEffect, useRef } from "react";
import { FaBook } from "react-icons/fa";
import { vnTitles } from "./vnLibrary.generated";

const normalizeTitle = (value: string) => value.toLowerCase().replace(/[^\p{L}\p{N}]+/gu, "");

const catalogTitleKeys = new Set(
  Object.keys(vnTitles)
    .map((appId) => normalizeTitle(vnTitles[appId]))
    .filter((key) => key.length >= 4)
);

const isCatalogApp = (appId: string) => Object.prototype.hasOwnProperty.call(vnTitles, appId);

const libraryEntries = (found: Record<string, GameEntry>): GameEntry[] =>
  Object.keys(found)
    .map((appId) => found[appId])
    .filter((game): game is GameEntry => Boolean(game))
    .sort((a, b) => String(a.name || "").localeCompare(String(b.name || "")));

const isCatalogShortcut = (name: string) => {
  const lowered = name.toLowerCase();
  if (
    !lowered ||
    lowered === "vn patch manager" ||
    lowered.indexOf("vn patch manager") >= 0 ||
    lowered.indexOf("visual novel patch manager") >= 0
  ) {
    return false;
  }
  const key = normalizeTitle(name);
  return key.length >= 4 && catalogTitleKeys.has(key);
};

interface GameEntry {
  app_id: string;
  name: string;
  is_installed: boolean;
  is_patched: boolean;
  has_local_patch: boolean;
  has_clean_backup: boolean;
  is_non_steam?: boolean;
  has_vndb_18_patch?: boolean;
  vndb_rating?: number;
}

interface PluginPayload {
  success?: boolean;
  error?: string;
  message?: string;
  job_id?: string;
  method?: string;
  status?: string;
  result?: unknown;
  logs?: string[];
  jobs?: PluginPayload[];
  log_line?: string;
  install_status?: string;
  install_error?: string;
  installed?: boolean;
  daemon?: boolean;
  local_path?: string;
  home?: string;
  path?: string;
  realpath?: string;
}

type Phase = "loading" | "install" | "daemon" | "folder" | "ready";
type MutationMethod = "apply_patch" | "restore_backup" | "fix_codecs" | "restore_via_steam";

const POLL_MS = 1000;
const MUTATION_METHODS = ["apply_patch", "restore_backup", "fix_codecs", "restore_via_steam"];

const getLibraryGames = callable<[], PluginPayload>("get_library_games");
const getJob = callable<[job_id: string], PluginPayload>("get_job");
const listJobs = callable<[], PluginPayload>("list_jobs");
const applyPatch = callable<[app_id: string], PluginPayload>("apply_patch");
const restoreBackup = callable<[app_id: string], PluginPayload>("restore_backup");
const fixCodecs = callable<[app_id: string], PluginPayload>("fix_codecs");
const restoreViaSteam = callable<[app_id: string], PluginPayload>("restore_via_steam");
const getSetup = callable<[], PluginPayload>("get_setup");
const installVnpm = callable<[], PluginPayload>("install_vnpm");
const getInstallStatus = callable<[], PluginPayload>("get_install_status");
const setPatchFolder = callable<[path: string], PluginPayload>("set_patch_folder");

function Content() {
  const [games, setGames] = useState<Record<string, GameEntry>>({});
  const [loading, setLoading] = useState(false);
  const [statusMsg, setStatusMsg] = useState("Ready");
  const [phase, setPhase] = useState<Phase>("loading");
  const [homePath, setHomePath] = useState("/home/deck");
  const alive = useRef(true);
  const timer = useRef<number | undefined>(undefined);
  const needsFolder = useRef(false);

  const resultError = (result: PluginPayload | undefined, fallback: string) => {
    if (result && typeof result.error === "string" && result.error) {
      return result.error;
    }
    return fallback;
  };

  const clearTimer = () => {
    if (timer.current !== undefined) {
      window.clearTimeout(timer.current);
      timer.current = undefined;
    }
  };

  const delay = () => new Promise<void>((resolve) => {
    timer.current = window.setTimeout(() => resolve(), POLL_MS);
  });

  const latestLog = (job: PluginPayload, fallback: string) => {
    if (job.logs && job.logs.length > 0) {
      return job.logs[job.logs.length - 1];
    }
    return fallback;
  };

  const pollJob = async (jobId: string, fallback: string): Promise<PluginPayload | undefined> => {
    while (alive.current) {
      const job = await getJob(jobId);
      if (!alive.current) {
        return undefined;
      }
      if (!job || job.success === false) {
        setStatusMsg(resultError(job, "Lost contact with the daemon"));
        return undefined;
      }
      if (job.status === "queued" || job.status === "running") {
        setStatusMsg(latestLog(job, fallback));
        await delay();
        continue;
      }
      return job;
    }
    return undefined;
  };

  const listedGame = (appId: string, game: GameEntry) => {
    if (game.is_non_steam) {
      return isCatalogShortcut(String(game.name || ""));
    }
    if (game.has_vndb_18_patch === true) {
      return true;
    }
    if (typeof game.has_vndb_18_patch === "boolean") {
      return false;
    }
    return isCatalogApp(appId);
  };

  const titledGame = (appId: string, game: GameEntry): GameEntry => {
    const name = String(game.name || "");
    const catalog = vnTitles[appId];
    if (catalog && (!name || name.startsWith("Steam App #"))) {
      return { ...game, name: catalog };
    }
    return game;
  };

  const applyScanResult = (job: PluginPayload) => {
    const gamesResult = job.result;
    if (
      job.status === "succeeded" &&
      gamesResult &&
      typeof gamesResult === "object" &&
      !Array.isArray(gamesResult)
    ) {
      const raw = gamesResult as Record<string, GameEntry>;
      const found: Record<string, GameEntry> = {};
      Object.keys(raw).forEach((appId) => {
        const game = raw[appId];
        if (game && listedGame(appId, game)) {
          found[appId] = titledGame(appId, game);
        }
      });
      setGames(found);
      if (needsFolder.current) {
        setStatusMsg("Choose a patch folder");
        return;
      }
      const count = Object.keys(found).length;
      setStatusMsg(count === 0 ? "No visual novels found" : "Found " + count + " VNs");
      return;
    }
    if (job.status === "failed") {
      setStatusMsg(job.error || "Scan failed");
      return;
    }
    if (job.status === "missing") {
      setStatusMsg("Job missing");
      return;
    }
    setStatusMsg("Scan failed");
  };

  const finishMutation = (job: PluginPayload, done: string) => {
    if (job.status === "missing") {
      setStatusMsg("Job missing");
      return false;
    }
    if (job.status === "failed") {
      setStatusMsg(job.error || "Unknown error");
      return false;
    }
    const outcome = job.result as { success?: boolean; error?: string } | undefined;
    if (outcome && outcome.success) {
      setStatusMsg(done);
      return true;
    }
    setStatusMsg((outcome && outcome.error) || "Unknown error");
    return false;
  };

  const runScan = async () => {
    setLoading(true);
    setStatusMsg(needsFolder.current ? "Choose a patch folder" : "Scanning visual novels...");
    try {
      const ticket = await getLibraryGames();
      if (!alive.current) {
        return;
      }
      if (!ticket?.success || !ticket.job_id) {
        setStatusMsg(resultError(ticket, "The daemon did not start"));
        return;
      }
      const job = await pollJob(ticket.job_id, "Scanning visual novels...");
      if (job) {
        applyScanResult(job);
      }
    } catch (e) {
      if (alive.current) {
        setStatusMsg("Error: " + e);
      }
    } finally {
      if (alive.current) {
        setLoading(false);
      }
    }
  };

  const submitMutation = (method: MutationMethod, appId: string) => {
    if (method === "apply_patch") {
      return applyPatch(appId);
    }
    if (method === "restore_backup") {
      return restoreBackup(appId);
    }
    if (method === "restore_via_steam") {
      return restoreViaSteam(appId);
    }
    return fixCodecs(appId);
  };

  const runMutation = async (method: MutationMethod, appId: string, working: string, done: string) => {
    setLoading(true);
    setStatusMsg(working);
    try {
      const ticket = await submitMutation(method, appId);
      if (!alive.current) {
        return;
      }
      if (!ticket?.success || !ticket.job_id) {
        setStatusMsg(resultError(ticket, "Unknown error"));
        return;
      }
      const job = await pollJob(ticket.job_id, working);
      if (job && finishMutation(job, done)) {
        await runScan();
      }
    } catch (e) {
      if (alive.current) {
        setStatusMsg("Error: " + e);
      }
    } finally {
      if (alive.current) {
        setLoading(false);
      }
    }
  };

  const continueWhenReady = async () => {
    try {
      const listed = await listJobs();
      const jobs = listed?.jobs ?? [];
      const mutation = jobs.find((job) =>
        !!job.job_id &&
        (job.status === "queued" || job.status === "running") &&
        !!job.method &&
        MUTATION_METHODS.indexOf(job.method) >= 0
      );
      if (mutation?.job_id) {
        setLoading(true);
        const job = await pollJob(mutation.job_id, "Working...");
        if (job && finishMutation(job, "Finished")) {
          await runScan();
        } else if (alive.current) {
          setLoading(false);
        }
        return;
      }
      const scan = jobs.find((job) =>
        job.method === "scan_games" &&
        !!job.job_id &&
        (job.status === "queued" || job.status === "running")
      );
      if (scan?.job_id) {
        setLoading(true);
        setStatusMsg("Scanning visual novels...");
        const job = await pollJob(scan.job_id, "Scanning visual novels...");
        if (job) {
          applyScanResult(job);
        }
        if (alive.current) {
          setLoading(false);
        }
        return;
      }
    } catch (e) {
      if (alive.current) {
        setStatusMsg("Error: " + e);
      }
    }
    if (alive.current) {
      await runScan();
    }
  };

  const watchInstall = async () => {
    setLoading(true);
    setPhase("install");
    try {
      while (alive.current) {
        const status = await getInstallStatus();
        if (!alive.current) {
          return;
        }
        if (status?.log_line) {
          setStatusMsg(status.log_line);
        }
        if (status?.status === "succeeded") {
          return;
        }
        if (status?.status === "failed" || status?.status === "idle") {
          setStatusMsg(status.error || status.log_line || "Install failed");
          return;
        }
        await delay();
      }
    } catch (e) {
      if (alive.current) {
        setStatusMsg("Error: " + e);
      }
    } finally {
      if (alive.current) {
        setLoading(false);
      }
    }
  };

  const boot = async () => {
    try {
      const setup = await getSetup();
      if (!alive.current) {
        return;
      }
      setHomePath(setup.home || "/home/deck");
      if (setup.install_status === "running") {
        await watchInstall();
        if (alive.current) {
          await boot();
        }
        return;
      }
      if (!setup.installed) {
        setPhase("install");
        setGames({});
        setStatusMsg("VNPM is not installed");
        return;
      }
      if (!setup.daemon) {
        setPhase("daemon");
        setGames({});
        setStatusMsg(setup.log_line || "The daemon did not start");
        return;
      }
      needsFolder.current = !String(setup.local_path || "").trim();
      setPhase(needsFolder.current ? "folder" : "ready");
      if (needsFolder.current) {
        setStatusMsg("Choose a patch folder");
      }
      await continueWhenReady();
    } catch (e) {
      if (alive.current) {
        setStatusMsg("Error: " + e);
      }
    }
  };

  const runInstall = async () => {
    setLoading(true);
    setStatusMsg("Installing VNPM...");
    try {
      const started = await installVnpm();
      if (!alive.current) {
        return;
      }
      if (!started?.success) {
        setStatusMsg(resultError(started, "Install failed"));
        return;
      }
      await watchInstall();
      if (alive.current) {
        await boot();
      }
    } catch (e) {
      if (alive.current) {
        setStatusMsg("Error: " + e);
      }
    } finally {
      if (alive.current) {
        setLoading(false);
      }
    }
  };

  const chooseFolder = async () => {
    setLoading(true);
    try {
      const picked = await openFilePicker(FileSelectionType.FOLDER, homePath);
      if (!alive.current) {
        return;
      }
      const folder = picked?.realpath || picked?.path || "";
      if (!folder) {
        return;
      }
      const saved = await setPatchFolder(folder);
      if (!saved?.success) {
        setStatusMsg(resultError(saved, "Could not save the patch folder"));
        return;
      }
      needsFolder.current = false;
      setPhase("ready");
      await runScan();
    } catch (e) {
      if (alive.current) {
        setStatusMsg("Error: " + e);
      }
    } finally {
      if (alive.current) {
        setLoading(false);
      }
    }
  };

  const confirmRestore = (game: GameEntry, method: "restore_backup" | "restore_via_steam") => {
    const viaSteam = method === "restore_via_steam";
    showModal(
      <ConfirmModal
        strTitle={viaSteam ? "Restore via Steam" : "Restore"}
        strDescription={
          viaSteam
            ? "Steam will verify the files for " + game.name + "."
            : "Restore " + game.name + " from its clean backup."
        }
        strOKButtonText="Restore"
        strCancelButtonText="Cancel"
        bDestructiveWarning
        onOK={() => {
          void runMutation(
            method,
            game.app_id,
            viaSteam ? "Restoring " + game.name + " via Steam..." : "Restoring " + game.name + "...",
            "Restore finished",
          );
        }}
      />
    );
  };

  useEffect(() => {
    alive.current = true;
    void boot();
    return () => {
      alive.current = false;
      clearTimer();
    };
  }, []);

  const gameState = (game: GameEntry) => {
    if (game.is_patched) {
      return "Patched";
    }
    if (game.has_local_patch) {
      return "Patch ready";
    }
    return "Not patched";
  };

  const entries = libraryEntries(games);

  return (
    <Fragment>
      <PanelSection title="VN Patch Manager">
        <PanelSectionRow>
          <div>{statusMsg}</div>
        </PanelSectionRow>
        <PanelSectionRow>
          <ButtonItem layout="below" onClick={() => void boot()} disabled={loading}>
            Refresh
          </ButtonItem>
        </PanelSectionRow>
        {phase === "install" && (
          <PanelSectionRow>
            <ButtonItem layout="below" onClick={() => void runInstall()} disabled={loading}>
              Install VNPM
            </ButtonItem>
          </PanelSectionRow>
        )}
        {phase === "folder" && (
          <PanelSectionRow>
            <ButtonItem layout="below" onClick={() => void chooseFolder()} disabled={loading}>
              Choose folder
            </ButtonItem>
          </PanelSectionRow>
        )}
      </PanelSection>
      <style>{`
        .vnpm-library { display: flex; flex-direction: column; width: 100%; }
        .vnpm-game { display: flex; flex-direction: column; width: 100%; box-sizing: border-box; padding: 10px 0; }
        .vnpm-game + .vnpm-game { border-top: 1px solid rgba(255, 255, 255, 0.18); }
        .vnpm-game-name { font-size: 16px; line-height: 1.3; }
        .vnpm-game-state { opacity: 0.75; margin: 2px 0 6px; }
      `}</style>
      <div className="vnpm-library">
        {entries.map((game) => (
          <div className="vnpm-game" key={game.app_id}>
            <div className="vnpm-game-name">{game.name}</div>
            <div className="vnpm-game-state">{gameState(game)}</div>
            {game.has_local_patch && !game.is_patched && (
              <DialogButton
                style={{ width: "100%", marginTop: "6px" }}
                disabled={loading}
                onClick={() => void runMutation("apply_patch", game.app_id, "Applying patch for " + game.name + "...", "Patch applied successfully!")}
              >
                {"Apply patch for " + game.name}
              </DialogButton>
            )}
            {(game.is_patched || game.has_clean_backup) && (
              <DialogButton
                style={{ width: "100%", marginTop: "6px" }}
                disabled={loading}
                onClick={() => confirmRestore(game, "restore_backup")}
              >
                {"Restore " + game.name}
              </DialogButton>
            )}
            {game.is_installed && !game.has_clean_backup && (
              <DialogButton
                style={{ width: "100%", marginTop: "6px" }}
                disabled={loading}
                onClick={() => confirmRestore(game, "restore_via_steam")}
              >
                {"Restore " + game.name + " via Steam"}
              </DialogButton>
            )}
            {game.is_installed && (
              <DialogButton
                style={{ width: "100%", marginTop: "6px" }}
                disabled={loading}
                onClick={() => void runMutation("fix_codecs", game.app_id, "Fixing codecs for " + game.name + "...", "Codec fixes applied")}
              >
                {"Fix codecs for " + game.name}
              </DialogButton>
            )}
          </div>
        ))}
      </div>
    </Fragment>
  );
}

export default definePlugin(() => {
  return {
    name: "VN Patch Manager",
    titleView: <div className={staticClasses.Title}>VN Patch Manager</div>,
    content: <Content />,
    icon: <FaBook />,
    onDismount() {},
  };
});
