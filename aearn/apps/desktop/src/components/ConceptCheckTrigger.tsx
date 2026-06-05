type ConceptCheckTriggerProps = {
  disabled: boolean;
  loading: boolean;
  triggered: boolean;
  errorMessage: string | null;
  onTrigger: () => void;
};

export function ConceptCheckTrigger({
  disabled,
  loading,
  triggered,
  errorMessage,
  onTrigger,
}: ConceptCheckTriggerProps) {
  return (
    <article className="concept-trigger-card" aria-label="开始概念检验">
      <div>
        <h3>准备好了吗？</h3>
        <p>我会出几道题检验你的理解；如果刚才引用过文档，我会优先关注那些卡点。</p>
        {errorMessage && <p className="concept-trigger-error">{errorMessage}</p>}
      </div>
      <button className="btn primary" type="button" disabled={disabled || loading || triggered} onClick={onTrigger}>
        {triggered ? "已进入概念检验" : loading ? "正在生成…" : "✓ 开始概念检验"}
      </button>
    </article>
  );
}
