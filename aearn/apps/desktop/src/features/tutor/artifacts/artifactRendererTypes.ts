import type {
  TutorArtifactAction,
  TutorArtifactAttemptDetail,
  TutorArtifactSourceReference,
  TutorPublicArtifactItem,
} from "../../../types";

export type TutorArtifactActionRequest = {
  artifact: TutorPublicArtifactItem;
  action: TutorPublicArtifactItem["allowed_actions"][number];
  payload?: TutorArtifactAction;
};

export type TutorArtifactActionHandler = (
  request: TutorArtifactActionRequest,
) => Promise<TutorPublicArtifactItem | void> | TutorPublicArtifactItem | void;

export type TutorArtifactAttemptLoadRequest = {
  artifact: TutorPublicArtifactItem;
  attemptId: string;
};

export type TutorArtifactAttemptLoader = (
  request: TutorArtifactAttemptLoadRequest,
) => Promise<TutorArtifactAttemptDetail>;

export type TutorArtifactReturnToSourceRequest = {
  resultArtifact: TutorPublicArtifactItem;
  sourceArtifactReference: TutorArtifactSourceReference & { kind: "artifact" };
};

export type TutorArtifactReturnToSource = (
  request: TutorArtifactReturnToSourceRequest,
) => void;
