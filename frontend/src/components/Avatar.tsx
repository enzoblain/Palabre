import { avatarHue } from "../util";

export function Avatar({ name, boss = false, size = 32 }: { name: string; boss?: boolean; size?: number }) {
  const style = { width: size, height: size, fontSize: size * 0.42, "--hue": avatarHue(name) } as React.CSSProperties;
  return (
    <span className={`avatar${boss ? " avatar-boss" : ""}`} style={style}>
      {name.slice(0, 1).toUpperCase()}
    </span>
  );
}
