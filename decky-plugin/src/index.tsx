import {
  definePlugin,
  ServerAPI,
  staticClasses,
  PanelSection,
  PanelSectionRow,
  ButtonItem,
  Field,
} from "@decky/ui";
import { useState, useEffect, VFC } from "react";
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
}

const Content: VFC<{ serverAPI: ServerAPI }> = ({ serverAPI }) => {
  const [games, setGames] = useState<Record<string, GameEntry>>({});
  const [loading, setLoading] = useState(false);
  const [statusMsg, setStatusMsg] = useState("Ready");

  const resultError = (result: PluginPayload | undefined, fallback: string) => {
    if (result && typeof result.error === "string" && result.error) {
      return result.error;
    }
    return fallback;
  };

  const refreshLibrary = async () => {
    setLoading(true);
    setStatusMsg("Scanning visual novels...");
    try {
      const res = await serverAPI.callPluginMethod<{}, PluginPayload>("get_library_games", {});
      const payload = res.result;
      if (res.success && payload?.success && payload.games && typeof payload.games === "object") {
        setGames(payload.games);
        setStatusMsg("Found " + Object.keys(payload.games).length + " VNs");
      } else {
        setStatusMsg(resultError(payload, "Daemon not connected (run 'vnpm --daemon')"));
      }
    } catch (e) {
      setStatusMsg("Error: " + e);
    } finally {
      setLoading(false);
    }
  };

  const runMutation = async (method: "apply_patch" | "restore_backup" | "fix_codecs", appId: string, working: string, done: string) => {
    setLoading(true);
    setStatusMsg(working);
    try {
      const res = await serverAPI.callPluginMethod<{ app_id: string }, PluginPayload>(method, { app_id: appId });
      if (res.success && res.result?.success) {
        setStatusMsg(done);
        await refreshLibrary();
      } else {
        setStatusMsg(resultError(res.result, "Unknown error"));
      }
    } catch (e) {
      setStatusMsg("Error: " + e);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    refreshLibrary();
  }, []);

  return (
    <PanelSection title="VN Patch Manager">
      <PanelSectionRow>
        <Field label="Status" description={statusMsg}>
          <ButtonItem onClick={refreshLibrary} disabled={loading}>
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
