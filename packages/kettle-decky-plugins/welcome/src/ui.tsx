// What the Welcome pages share: text styles.
import { ReactNode } from "react";

export const small = { fontSize: "12px", lineHeight: "16px" };

export const Text = ({ children }: { children: ReactNode }) => <div style={{ lineHeight: "22px", maxWidth: "720px" }}>{children}</div>;

// A page's section heading, like the desktop Welcome's
export const Heading = ({ children }: { children: ReactNode }) => (
  <h3 style={{ margin: "24px 0 4px", maxWidth: "720px" }}>{children}</h3>
);
