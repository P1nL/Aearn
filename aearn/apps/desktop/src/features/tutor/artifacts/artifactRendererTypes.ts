import type {
  TutorArtifactAttemptDetail,
  TutorArtifactSourceReference,
  TutorPublicArtifactItem,
} from "../../../types";

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
