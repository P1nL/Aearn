import { useEffect, useRef, useState } from "react";

import type { TeachingActionDescriptor, TeachingActionShelf } from "../../types";

type ComposerActionShelfProps = {
  projection: TeachingActionShelf | null;
  pendingActionKey: string | null;
  onAction: (descriptor: TeachingActionDescriptor) => void;
};

export function ComposerActionShelf({ projection, pendingActionKey, onAction }: ComposerActionShelfProps) {
  const [overflowOpen, setOverflowOpen] = useState(false);
  const overflowRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!overflowOpen) return;
    function close(event: MouseEvent) {
      if (overflowRef.current && event.target instanceof Node && !overflowRef.current.contains(event.target)) setOverflowOpen(false);
    }
    globalThis.document?.addEventListener("mousedown", close);
    return () => globalThis.document?.removeEventListener("mousedown", close);
  }, [overflowOpen]);

  if (!projection || projection.state === "runtime_active" || projection.state === "blocking_request") return null;
  const visibleSecondary = projection.secondary_actions.slice(0, 3);
  const overflow = [...projection.secondary_actions.slice(3), ...projection.overflow_actions];

  return (
    <section className={`composer-action-shelf state-${projection.state}`} aria-label="教学下一步">
      <div className="composer-action-shelf-secondary">
        {visibleSecondary.map((descriptor) => <ShelfButton key={descriptor.key} descriptor={descriptor} pendingActionKey={pendingActionKey} onAction={onAction} />)}
        {overflow.length > 0 ? (
          <div className="composer-action-shelf-overflow" ref={overflowRef}>
            <button className="tutor-compact-button quiet" type="button" aria-haspopup="menu" aria-expanded={overflowOpen} onClick={() => setOverflowOpen((current) => !current)}>更多</button>
            {overflowOpen ? <div className="composer-action-shelf-menu" role="menu">{overflow.map((descriptor) => <ShelfButton key={descriptor.key} descriptor={descriptor} pendingActionKey={pendingActionKey} onAction={(item) => { setOverflowOpen(false); onAction(item); }} menu />)}</div> : null}
          </div>
        ) : null}
      </div>
      {projection.primary_action ? <ShelfButton descriptor={projection.primary_action} pendingActionKey={pendingActionKey} onAction={onAction} primary /> : <span className="composer-action-shelf-placeholder" aria-live="polite">{projection.state === "completion" ? "当前知识点已完成，没有可用的下一节点。" : "继续阅读，或在 Composer 中提出问题。"}</span>}
    </section>
  );
}

function ShelfButton({ descriptor, pendingActionKey, onAction, primary = false, menu = false }: {
  descriptor: TeachingActionDescriptor;
  pendingActionKey: string | null;
  onAction: (descriptor: TeachingActionDescriptor) => void;
  primary?: boolean;
  menu?: boolean;
}) {
  const pending = pendingActionKey === descriptor.key;
  const disabled = !descriptor.enabled || pendingActionKey !== null;
  return <button
    className={primary ? "tutor-primary-button composer-action-primary" : "tutor-compact-button quiet"}
    type="button"
    role={menu ? "menuitem" : undefined}
    disabled={disabled}
    aria-busy={pending}
    title={descriptor.disabled_reason ?? descriptor.label}
    onClick={() => onAction(descriptor)}
  >{pending ? "正在确认……" : descriptor.label}</button>;
}
