type SystemCardProps = {
  title: string;
  body: string;
  actionLabel?: string;
  onAction?: () => void;
};

export function SystemCard({ title, body, actionLabel, onAction }: SystemCardProps) {
  return (
    <article className="system-card">
      <h3>{title}</h3>
      <p>{body}</p>
      {actionLabel && onAction && (
        <button className="btn primary ghost-btn" type="button" onClick={onAction}>
          {actionLabel}
        </button>
      )}
    </article>
  );
}
