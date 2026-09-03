interface ManagementDetailsProps {
  cards: Array<[string, string]>;
  description: string;
}

export default function ManagementDetails({
  cards,
  description,
}: ManagementDetailsProps) {
  return (
    <>
      <div className="readonly-intro">
        <span>只读占位 · 路由验证</span>
        <p>{description}</p>
      </div>
      <div className="placeholder-grid">
        {cards.map(([title, content]) => (
          <article key={title}>
            <span aria-hidden="true">✦</span>
            <h2>{title}</h2>
            <p>{content}</p>
          </article>
        ))}
      </div>
    </>
  );
}
