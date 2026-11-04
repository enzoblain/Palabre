import { useCallback, useEffect, useState } from "react";
import { type ProjectPlatform, api } from "../api";
import { isAppleModeOff } from "../apple";
import { useI18n } from "../i18n";
import { WarningIcon } from "./Icons";

type MacState = "loading" | "error" | "modeOff" | "noMac" | "ready";

/** Link to the Mac section of the settings, shown wherever a missing Mac is explained. */
export function ConnectMacLink() {
  const { t } = useI18n();
  return <a className="link" href="#/settings">{t("new.connectMac")}</a>;
}

/** Standard or Apple/Swift: the Apple choice needs the mode on and a connected Mac, and says why when it cannot be used. */
export function ProjectTypeChoice({ platform, onChange }: { platform: ProjectPlatform; onChange: (platform: ProjectPlatform) => void }) {
  const { t } = useI18n();
  const [mac, setMac] = useState<MacState>("loading");

  const check = useCallback(async () => {
    setMac("loading");
    try {
      const hosts = await api.listAppleHosts();
      setMac(hosts.some((host) => host.connected && !host.revoked_at) ? "ready" : "noMac");
    } catch (err) {
      setMac(isAppleModeOff(err) ? "modeOff" : "error");
    }
  }, []);
  useEffect(() => { void check(); }, [check]);

  const appleUsable = mac === "ready";
  return (
    <fieldset className="type-choice">
      <legend>{t("new.type")}</legend>
      <label className="choice">
        <input type="radio" name="platform" checked={platform === "generic"} onChange={() => onChange("generic")} />
        <span><strong>{t("new.typeStandard")}</strong><span className="muted block">{t("new.typeStandardHelp")}</span></span>
      </label>
      {/* aria-disabled, not disabled: the radio stays in the tab order and its reason stays readable */}
      <label className="choice">
        <input type="radio" name="platform" checked={platform === "apple"} aria-disabled={!appleUsable}
          aria-describedby="apple-help" onChange={() => { if (appleUsable) onChange("apple"); }} />
        <span><strong>{t("new.typeApple")}</strong><span className="muted block">{t("new.typeAppleHelp")}</span></span>
      </label>
      <div id="apple-help" className="choice-help">
        {mac === "loading" && <span className="muted" role="status">{t("new.macChecking")}</span>}
        {mac === "error" && (
          <span className="error with-icon"><WarningIcon size={16} />{t("new.macCheckFailed")}{" "}
            <button type="button" className="btn btn-small" onClick={() => void check()}>{t("common.retry")}</button></span>
        )}
        {mac === "modeOff" && <span className="error with-icon"><WarningIcon size={16} />{t("new.appleModeOff")}</span>}
        {mac === "noMac" && <span className="error with-icon"><WarningIcon size={16} />{t("new.noMac")}</span>}
        {platform === "apple" && <span className="muted block">{t("new.appleToml")}</span>}
      </div>
      {mac === "noMac" && <ConnectMacLink />}
    </fieldset>
  );
}
