export { LearningRouteCard } from "./LearningRouteCard";
export { ExerciseCard } from "./ExerciseCard";
export { SubmitResultCard } from "./SubmitResultCard";
export { ReviewRecallCard } from "./ReviewRecallCard";
export { ProgressSummaryCard } from "./ProgressSummaryCard";
export type { ToolUIProps, LearningRouteArgs, ExerciseCardArgs, SubmitResultArgs, ReviewRecallArgs, ProgressSummaryArgs } from "./types";

import type { ToolUIProps } from "./types";
import type { LearningRouteArgs, ExerciseCardArgs, SubmitResultArgs, ReviewRecallArgs, ProgressSummaryArgs } from "./types";
import { LearningRouteCard } from "./LearningRouteCard";
import { ExerciseCard } from "./ExerciseCard";
import { SubmitResultCard } from "./SubmitResultCard";
import { ReviewRecallCard } from "./ReviewRecallCard";
import { ProgressSummaryCard } from "./ProgressSummaryCard";

type ToolUIEntry = {
  component: React.ComponentType<ToolUIProps<any>>;
  description: string;
};

export const toolUIRegistry: Record<string, ToolUIEntry> = {
  show_learning_route: {
    component: LearningRouteCard as React.ComponentType<ToolUIProps<any>>,
    description: "Display the user's learning route with modules and knowledge points",
  },
  show_exercise: {
    component: ExerciseCard as React.ComponentType<ToolUIProps<any>>,
    description: "Present a code exercise for the user to complete",
  },
  show_submit_result: {
    component: SubmitResultCard as React.ComponentType<ToolUIProps<any>>,
    description: "Show exercise submission results with scoring breakdown",
  },
  show_review_recall: {
    component: ReviewRecallCard as React.ComponentType<ToolUIProps<any>>,
    description: "Prompt the user to recall a knowledge point before review",
  },
  show_progress_summary: {
    component: ProgressSummaryCard as React.ComponentType<ToolUIProps<any>>,
    description: "Display overall learning progress and stats",
  },
};

export function resolveToolUI(toolName: string): ToolUIEntry | undefined {
  return toolUIRegistry[toolName];
}
