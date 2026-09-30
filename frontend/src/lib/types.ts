export type FileType =
  | "calendario"
  | "docenti"
  | "classi"
  | "materie"
  | "assegnazioni"
  | "accoppiamenti";

export interface UploadResult {
  status: string;
  file_id: string;
  file_type: FileType;
  preview?: Record<string, unknown>;
}

export interface ValidationIssue {
  [key: string]: string;
}

export interface ValidationWarning {
  entity: string;
  issue: string;
}

export interface FileValidation {
  success: boolean;
  preview?: Record<string, number | string>;
  warnings: ValidationWarning[];
  errors: ValidationIssue[];
}

export interface ValidationResponse {
  status: string;
  results: Partial<Record<FileType, FileValidation>>;
  overall_status: string;
  can_proceed: boolean;
}

export interface Week {
  start: string;
  end: string;
  week_num: number;
}

export interface AvailabilitySlot {
  ora_inizio: string;
  ora_fine: string;
  disponibile: boolean;
}

export type Giorno = "lunedi" | "martedi" | "mercoledi" | "giovedi" | "venerdi";

export type GiorniFasce = Record<Giorno, AvailabilitySlot[]>;

export interface TeacherAvailability {
  teacher_id: string;
  week_start: string;
  giorni_fasce: GiorniFasce;
}

export interface AvailabilityStatus {
  week_complete: boolean;
  total_teachers: number;
  teachers_with_availability: number;
  ready_to_generate: boolean;
}

export interface Teacher {
  teacher_id: string;
  nome: string;
  email: string;
  tipo: "ASSUNTO" | "CONTRATTO";
  materia?: string;
}

export interface SchoolClass {
  classe_id: string;
  nome: string;
  n_studenti?: number;
}

export interface Subject {
  materia_id: string;
  nome: string;
  tipo: "TEORIA" | "PRATICA";
  peso_cognitivo?: "ALTO" | "MEDIO" | "BASSO";
}

export interface Assignment {
  assignment_id: string;
  docente_id: string;
  classe_id: string;
  materia_id: string;
  ore_totali: number;
  ore_erogate?: number;
}

export interface ClassPairing {
  pairing_id: string;
  classe_a_id: string;
  classe_b_id: string;
  materia_id: string;
  docente_id?: string;
}

export interface CalendarEntry {
  date_id: string;
  data: string;
  gruppo?: string | null;
  ore_max_giornata: 4 | 5 | 6;
  ora_inizio_min?: number | null;
  flag_chiusura: boolean;
  flag_stage_classe_id?: string | null;
  flag_stage_gruppo?: boolean;
}

export interface SlotLezione {
  slot_id: string;
  classe_id: string;
  docente_id: string;
  materia_id: string;
  giorno: string;
  ora_inizio: number;
  ora_fine: number;
  accoppiata?: boolean;
  classe_accoppiata_id?: string;
  materia_tipo?: "TEORIA" | "PRATICA";
  conflitto?: boolean;
  /** `chiave` of every conflict this lesson is part of. */
  conflitto_chiavi?: string[];
  indisponibile?: boolean;
  materia_nome?: string;
  docente_nome?: string;
  classe_nome?: string;
}

export interface Conflict {
  conflict_id: string;
  /** Stable id (unlike conflict_id): what approve/reject is stored against. */
  chiave?: string;
  description: string;
  suggested_action?: {
    action_type: string;
    label: string;
  };
  classe_id?: string | null;
  docente_id?: string | null;
  giorno?: string | null;
  /** Hours (8-13) left without a lesson: the grid paints those empty cells red. */
  ore?: number[];
}

export interface Schedule {
  schedule_id: string;
  week_start: string;
  stato?: "BOZZA" | "APPROVATO";
  quality_score: number;
  quality_level?: string;
  n_soft_conflicts?: number;
  conflicts?: Conflict[];
  slots: SlotLezione[];
  classes?: SchoolClass[];
  teachers?: Teacher[];
  stage_cells?: { classe_id: string; classe_nome: string; giorno: string }[];
}

export interface ChatMessage {
  role: "admin" | "ai";
  text: string;
  timestamp?: string;
  streaming?: boolean;
  actions?: { label: string; action_id: string }[];
}

export interface ScheduleFeedback {
  id: string;
  voto: number;
  motivi: string[];
  nota: string | null;
  quality_score: number | null;
  quality_level: string | null;
  n_conflitti_soft: number | null;
  stato: "BOZZA" | "APPROVATO" | null;
  created_at: string | null;
}

export interface ScheduleFeedbackData {
  motivi_disponibili: { code: string; label: string }[];
  current: ScheduleFeedback | null;
  history: ScheduleFeedback[];
  schedule: { quality_score: number | null; quality_level: string | null; stato: string | null };
}
