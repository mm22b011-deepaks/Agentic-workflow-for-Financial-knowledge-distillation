import type { ButtonHTMLAttributes } from "react";
import { Icon } from "./Icon";
export function Button({
  icon,
  title,
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { icon: string; title: string }) {
  return (
    <button {...props} type="button" title={title} aria-label={title}>
      <Icon name={icon} />
      {props.children}
    </button>
  );
}
