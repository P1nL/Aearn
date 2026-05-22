import { create } from "zustand";
import { toast } from "sonner";

import { updateUserPreferences } from "../api";
import type { UserPreferencesUpdate, UserProfile } from "../types";
import type { SettingsKey } from "../appTypes";
import { getErrorInfo } from "../lib/errorMessages";
import { isRecord } from "../lib/typeGuards";

type SettingsFormState = {
  displayName: string;
  learningStyle: string;
  teachingPreference: string;
  encouragementPreference: string;
  profession: string;
  backgroundContext: string;
  preferredWeekday: string;
  preferredStart: string;
  preferredEnd: string;
  reminderEnabled: boolean;
  reminderChannel: string;
  quietHoursStart: string;
  quietHoursEnd: string;
};

type SettingsStore = {
  settingsTab: SettingsKey;
  form: SettingsFormState;
  saveState: "idle" | "saving" | "saved" | "error";
  saveErrorMessage: string | null;

  setTab: (tab: SettingsKey) => void;
  updateField: (field: keyof SettingsFormState, value: string | boolean) => void;
  syncFromUser: (user: UserProfile) => void;
  save: (userId: string) => Promise<UserProfile | null>;
  isDirty: (user: UserProfile | null) => boolean;
};

function emptyForm(): SettingsFormState {
  return {
    displayName: "",
    learningStyle: "",
    teachingPreference: "",
    encouragementPreference: "",
    profession: "",
    backgroundContext: "",
    preferredWeekday: "mon",
    preferredStart: "20:00",
    preferredEnd: "21:00",
    reminderEnabled: true,
    reminderChannel: "desktop",
    quietHoursStart: "23:00",
    quietHoursEnd: "08:00",
  };
}

function formFromUser(user: UserProfile): SettingsFormState {
  const firstSlot = Array.isArray(user.preferred_time_slots) ? user.preferred_time_slots[0] : null;
  const reminderPreference = isRecord(user.reminder_preference) ? user.reminder_preference : {};
  const quietHours = isRecord(reminderPreference.quiet_hours) ? reminderPreference.quiet_hours : {};
  const channels = Array.isArray(reminderPreference.channels)
    ? reminderPreference.channels.filter((item): item is string => typeof item === "string")
    : typeof reminderPreference.channel === "string"
      ? [reminderPreference.channel]
      : [];

  return {
    displayName: user.display_name,
    learningStyle: user.learning_style ?? "",
    teachingPreference: user.teaching_preference ?? "",
    encouragementPreference: user.encouragement_preference ?? "",
    profession: user.profession ?? "",
    backgroundContext: user.background_context ?? "",
    preferredWeekday: typeof firstSlot?.weekday === "string" ? firstSlot.weekday : "mon",
    preferredStart: typeof firstSlot?.start === "string" ? firstSlot.start : "20:00",
    preferredEnd: typeof firstSlot?.end === "string" ? firstSlot.end : "21:00",
    reminderEnabled: reminderPreference.enabled !== false,
    reminderChannel: channels[0] ?? "desktop",
    quietHoursStart: typeof quietHours.start === "string" ? quietHours.start : "23:00",
    quietHoursEnd: typeof quietHours.end === "string" ? quietHours.end : "08:00",
  };
}

function buildPayload(form: SettingsFormState): UserPreferencesUpdate {
  return {
    display_name: form.displayName.trim() || "Pinking",
    learning_style: nullableString(form.learningStyle),
    teaching_preference: nullableString(form.teachingPreference),
    encouragement_preference: nullableString(form.encouragementPreference),
    profession: nullableString(form.profession),
    background_context: nullableString(form.backgroundContext),
    preferred_time_slots: [
      {
        weekday: form.preferredWeekday.trim() || "mon",
        start: form.preferredStart.trim() || "20:00",
        end: form.preferredEnd.trim() || "21:00",
        timezone: "Asia/Shanghai",
      },
    ],
    reminder_preference: {
      enabled: form.reminderEnabled,
      channels: [form.reminderChannel.trim() || "desktop"],
      quiet_hours: {
        start: form.quietHoursStart.trim() || "23:00",
        end: form.quietHoursEnd.trim() || "08:00",
        timezone: "Asia/Shanghai",
      },
    },
  };
}

function nullableString(value: string): string | null {
  const trimmed = value.trim();
  return trimmed ? trimmed : null;
}

export const useSettingsStore = create<SettingsStore>((set, get) => ({
  settingsTab: "learning",
  form: emptyForm(),
  saveState: "idle",
  saveErrorMessage: null,

  setTab: (tab) => set({ settingsTab: tab }),

  updateField: (field, value) => {
    set((state) => ({
      form: { ...state.form, [field]: value },
      saveState: "idle",
      saveErrorMessage: null,
    }));
  },

  syncFromUser: (user) => {
    set({
      form: formFromUser(user),
      saveState: "idle",
      saveErrorMessage: null,
    });
  },

  save: async (userId) => {
    const { form } = get();
    const payload = buildPayload(form);
    set({ saveState: "saving", saveErrorMessage: null });
    try {
      const updated = await updateUserPreferences(userId, payload);
      set({ saveState: "saved" });
      toast.success("设置已保存");
      return updated;
    } catch (error) {
      const info = getErrorInfo(error);
      set({ saveState: "error", saveErrorMessage: info.message });
      toast.error(info.message);
      return null;
    }
  },

  isDirty: (user) => {
    if (!user) {
      return false;
    }
    const current = buildPayload(formFromUser(user));
    const next = buildPayload(get().form);
    return JSON.stringify(current) !== JSON.stringify(next);
  },
}));

export type { SettingsFormState };
