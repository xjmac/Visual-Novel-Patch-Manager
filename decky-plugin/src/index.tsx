import {
  definePlugin,
  ServerAPI,
  staticClasses,
  PanelSection,
  PanelSectionRow,
  ButtonItem,
  Field,
} from "@decky/ui";
import { useState, useEffect, useRef, VFC } from "react";
import { FaBook } from "react-icons/fa";

interface GameEntry {
  app_id: string;
  name: string;
  is_installed: boolean;
  is_patched: boolean;
  has_local_patch: boolean;
  has_clean_backup: boolean;
  vndb_rating?: number;
}

interface PluginPayload {
  success?: boolean;
  error?: string;
  games?: Record<string, GameEntry>;
  message?: string;
  job_id?: string;
  method?: string;
  status?: string;
  result?: unknown;
  logs?: string[];
  jobs?: PluginPayload[];
}

const POLL_MS = 1000;
const MUTATION_METHODS = ["apply_patch", "restore_backup", "fix_codecs", "restore_via_steam"];

const Content: VFC<{ serverAPI: ServerAPI }> = ({ serverAPI }) => {
  const [games, setGames] = useState<Record<string, GameEntry>>({});
  const [loading, setLoading] = useState(false);
  const [statusMsg, setStatusMsg] = useState("Ready");
  const alive = useRef(true);
  const timer = useRef<number | undefined>(undefined);

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

  const callMethod = async (method: string, args: object): Promise<PluginPayload | undefined> => {
    const res = await serverAPI.callPluginMethod<object, PluginPayload>(method, args);
    if (!res.success) {
      return undefined;
    }
    return res.result;
  };

  const latestLog = (job: PluginPayload, fallback: string) => {
    if (job.logs && job.logs.length > 0) {
      return job.logs[job.logs.length - 1];
    }
    return fallback;
  };

  const pollJob = async (jobId: string, fallback: string): Promise<PluginPayload | undefined> => {
    while (alive.current) {
      const job = await callMethod("get_job", { job_id: jobId });
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

  const applyScanResult = (job: PluginPayload) => {
    const gamesResult = job.result;
    if (
      job.status === "succeeded" &&
      gamesResult &&
      typeof gamesResult === "object" &&
      !Array.isArray(gamesResult)
    ) {
      const found = gamesResult as Record<string, GameEntry>;
      setGames(found);
      setStatusMsg("Found " + Object.keys(found).length + " VNs");
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
    setStatusMsg("Scanning visual novels...");
    try {
      const ticket = await callMethod("get_library_games", {});
      if (!alive.current) {
        return;
      }
      if (!ticket?.success || !ticket.job_id) {
        setStatusMsg(resultError(ticket, "Daemon not connected (run 'vnpm --daemon')"));
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

  const runMutation = async (method: "apply_patch" | "restore_backup" | "fix_codecs", appId: string, working: string, done: string) => {
    setLoading(true);
    setStatusMsg(working);
    try {
      const ticket = await callMethod(method, { app_id: appId });
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

  useEffect(() => {
    alive.current = true;

    const boot = async () => {
      try {
        const listed = await callMethod("list_jobs", {});
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

    boot();
    return () => {
      alive.current = false;
      clearTimer();
    };
  }, []);

  return (
    <PanelSection title="VN Patch Manager">
      <PanelSectionRow>
        <Field label="Status" description={statusMsg}>
          <ButtonItem onClick={runScan} disabled={loading}>
            Refresh
          </ButtonItem>
        </Field>
      </PanelSectionRow>

      {Object.values(games).map((game) => (
        <PanelSectionRow key={game.app_id}>
          <Field
            label={game.name}
            description={
              game.is_patched
                ? "● Patched & Verified"
                : game.has_local_patch
                ? "● 18+ Patch Ready"
                : "● Clean Unpatched"
            }
          >
            <div>
              {game.has_local_patch && !game.is_patched && (
                <ButtonItem
                  onClick={() => runMutation("apply_patch", game.app_id, "Applying patch for " + game.app_id + "...", "Patch applied successfully!")}
                  disabled={loading}
                >
                  Apply Patch
                </ButtonItem>
              )}
              {(game.is_patched || game.has_clean_backup) && (
                <ButtonItem
                  onClick={() => runMutation("restore_backup", game.app_id, "Restoring " + game.name + "...", "Restore finished")}
                  disabled={loading}
                >
                  Restore
                </ButtonItem>
              )}
              {game.is_installed && (
                <ButtonItem
                  onClick={() => runMutation("fix_codecs", game.app_id, "Fixing codecs for " + game.name + "...", "Codec fixes applied")}
                  disabled={loading}
                >
                  Fix codecs
                </ButtonItem>
              )}
            </div>
          </Field>
        </PanelSectionRow>
      ))}
    </PanelSection>
  );
};

export default definePlugin((serverAPI: ServerAPI) => {
  return {
    title: <div className={staticClasses.Title}>VN Patch Manager</div>,
    content: <Content serverAPI={serverAPI} />,
    icon: <FaBook />,
    onDismount() {},
  };
});
