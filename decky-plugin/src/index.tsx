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

const Content: VFC<{ serverAPI: ServerAPI }> = ({ serverAPI }) => {
  const [games, setGames] = useState<Record<string, GameEntry>>({});
  const [loading, setLoading] = useState(false);
  const [statusMsg, setStatusMsg] = useState("Ready");

  const refreshLibrary = async () => {
    setLoading(true);
    setStatusMsg("Scanning visual novels...");
    try {
      const res = await serverAPI.callPluginMethod<{}, Record<string, GameEntry>>("get_library_games", {});
      if (res.success && res.result) {
        setGames(res.result);
        setStatusMsg("Found " + Object.keys(res.result).length + " VNs");
      } else {
        setStatusMsg("Daemon not connected (run 'vnpm --daemon')");
      }
    } catch (e) {
      setStatusMsg("Error: " + e);
    } finally {
      setLoading(false);
    }
  };

  const applyPatch = async (appId: string) => {
    setLoading(true);
    setStatusMsg("Applying patch for " + appId + "...");
    try {
      const res = await serverAPI.callPluginMethod<{ app_id: string }, { success: boolean; error?: string }>("apply_patch", { app_id: appId });
      if (res.success && res.result?.success) {
        setStatusMsg("Patch applied successfully!");
        await refreshLibrary();
      } else {
        setStatusMsg("Patch failed: " + (res.result?.error || "Unknown error"));
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
            {game.has_local_patch && !game.is_patched && (
              <ButtonItem onClick={() => applyPatch(game.app_id)} disabled={loading}>
                Apply Patch
              </ButtonItem>
            )}
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
