export interface ClipJobInput {
  songId: string;
  userId: string;
  lyrics: string;
  audioKey: string;
  photoKey: string;
  title?: string;
  styleHint?: string;
}

export interface JobArtifacts {
  normalizedAudio?: string;
  vocals?: string;
  facesJson?: string;
  audioFeatures?: string;
  alignmentJson?: string;
  stylizedKeyframe?: string;
  loopVideos?: string[];
  finalClip?: string;
  thumbnail?: string;
}

export interface AlignmentSegment {
  index: number;
  line: string;
  start: number;
  end: number;
  confidence: number;
  is_instrumental?: boolean;
  words: AlignmentWord[];
}

export interface AlignmentWord {
  word: string;
  start: number;
  end: number;
  confidence: number;
  extended?: boolean;
}

export interface AlignmentResult {
  version: string;
  song_id: string;
  duration: number;
  language: string;
  alignment_method: string;
  confidence: number;
  segments: AlignmentSegment[];
}

export interface FaceDetection {
  id: number;
  bbox: [number, number, number, number];
  landmarks: number[][];
  size_relative: number;
  centrality: number;
  sharpness: number;
  is_primary: boolean;
  age_group: 'child' | 'adult';
}

export interface FacesResult {
  total_faces: number;
  total_persons: number;
  faces: FaceDetection[];
}
