import type { RunExerciseResponse, SubmitExerciseResponse } from "../types";
import { buildReviewCards } from "../lib/learningHelpers";

type ReviewRecapProps = {
  lastSubmit: SubmitExerciseResponse | null;
  lastRun: RunExerciseResponse | null;
};

export function ReviewRecap({ lastSubmit, lastRun }: ReviewRecapProps) {
  const cards = buildReviewCards(lastSubmit, lastRun);
  return (
    <div className="review-recap-grid">
      {cards.map((card, index) => (
        <article className={index === 0 ? "review-card active" : "review-card"} key={card.title}>
          <h3>{card.title}</h3>
          <p>{card.body}</p>
        </article>
      ))}
    </div>
  );
}
