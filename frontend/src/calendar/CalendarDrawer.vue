<script setup lang="ts">
import {
  computed,
  onBeforeUnmount,
  onMounted,
  reactive,
  ref,
  watch,
} from "vue";
import FullCalendar from "@fullcalendar/vue3";
import dayGridPlugin from "@fullcalendar/daygrid";
import timeGridPlugin from "@fullcalendar/timegrid";
import luxonPlugin from "@fullcalendar/luxon3";
import interactionPlugin from "@fullcalendar/interaction";
import zhCn from "@fullcalendar/core/locales/zh-cn";
import type { CalendarOptions } from "@fullcalendar/core";
import { errorMessage, requestJson } from "../api/http";
import { useConversation } from "../conversation/useConversation";
import {
  calendarOpen,
  calendarTarget,
  type CalendarEvent,
  type Subscription,
} from "./calendarState";
import { localInput, instant, followingDate } from "./calendarDates";
const { sessions, sessionId } = useConversation();
const calendar = ref<InstanceType<typeof FullCalendar>>();
const error = ref(""),
  busy = ref(false),
  loading = ref(false),
  editing = ref(false),
  deleting = ref(false),
  tab = ref("calendar");
const events = ref<CalendarEvent[]>([]),
  subscriptions = ref<Subscription[]>([]);
const selected = ref<CalendarEvent>();
const range = ref({ start: "", end: "" });
const scope = ref("single");
const zone =
  Intl.DateTimeFormat().resolvedOptions().timeZone || "Asia/Shanghai";
const draft = reactive({
  title: "",
  detail: "",
  start_at: "",
  end_at: "",
  all_day: false,
  timezone: zone,
  recurrence: "none",
  reminder_minutes: 10 as number | null,
});
const startInput = computed({
  get: () => (draft.all_day ? draft.start_at.slice(0, 10) : draft.start_at),
  set: (value: string) => {
    draft.start_at = draft.all_day ? value + "T00:00" : value;
  },
});
const endInput = computed({
  get: () => (draft.all_day ? draft.end_at.slice(0, 10) : draft.end_at),
  set: (value: string) => {
    draft.end_at = draft.all_day ? value + "T00:00" : value;
  },
});
function setAllDay() {
  if (draft.all_day) {
    draft.start_at = draft.start_at.slice(0, 10) + "T00:00";
    draft.end_at = draft.end_at.slice(0, 10) + "T00:00";
    if (draft.end_at <= draft.start_at)
      draft.end_at = followingDate(draft.start_at) + "T00:00";
  }
}
const sub = reactive({
  id: "",
  title: "每日安排",
  time: "08:00",
  timezone: zone,
  recurrence: "weekdays",
  weekday: 0,
  session_id: "",
  enabled: true,
});
const subEditing = ref(false),
  subDeleting = ref(false);
let revision = 0,
  disposed = false;
async function loadEvents() {
  if (!range.value.start) return;
  const rev = ++revision;
  loading.value = true;
  try {
    const data = await requestJson<{ events: CalendarEvent[] }>(
      `/api/calendar/events?${new URLSearchParams(range.value)}`,
    );
    if (rev === revision && !disposed) {
      events.value = data.events;
      error.value = "";
    }
  } catch (e) {
    if (rev === revision && !disposed) error.value = errorMessage(e);
  } finally {
    if (rev === revision && !disposed) loading.value = false;
  }
}
async function loadSubscriptions() {
  try {
    subscriptions.value = (
      await requestJson<{ subscriptions: Subscription[] }>(
        "/api/calendar/subscriptions",
      )
    ).subscriptions;
  } catch (e) {
    error.value = errorMessage(e);
  }
}
function edit(item?: CalendarEvent, start?: string) {
  selected.value = item;
  scope.value = "single";
  deleting.value = false;
  const time = start
    ? new Date(start.length === 10 ? `${start}T09:00` : start)
    : new Date();
  time.setSeconds(0, 0);
  Object.assign(
    draft,
    item
      ? {
          title: item.title,
          detail: item.detail,
          all_day: item.all_day,
          timezone: item.timezone,
          recurrence: item.recurrence,
          reminder_minutes: item.reminder_minutes,
          start_at: localInput(item.start_at, item.timezone),
          end_at: localInput(item.end_at, item.timezone),
        }
      : {
          title: "",
          detail: "",
          start_at: localInput(time.toISOString()),
          end_at: localInput(new Date(time.getTime() + 3600000).toISOString()),
          all_day: false,
          timezone: zone,
          recurrence: "none",
          reminder_minutes: 10,
        },
  );
  editing.value = true;
}
function endpoint() {
  const item = selected.value;
  if (!item) return "/api/calendar/events";
  return `/api/calendar/events/${encodeURIComponent(item.id)}?${new URLSearchParams({ scope: scope.value, occurrence_start: item.occurrence_start || item.start_at })}`;
}
async function save(remove = false) {
  if (busy.value) return;
  if (!remove && draft.end_at <= draft.start_at) {
    error.value = "结束时间需要晚于开始时间。";
    return;
  }
  busy.value = true;
  error.value = "";
  try {
    await requestJson(endpoint(), {
      method: remove ? "DELETE" : selected.value ? "PUT" : "POST",
      body: remove
        ? undefined
        : JSON.stringify({
            ...draft,
            start_at: instant(draft.start_at, draft.timezone),
            end_at: instant(draft.end_at, draft.timezone),
          }),
    });
    editing.value = false;
    await loadEvents();
  } catch (e) {
    error.value = errorMessage(e);
  } finally {
    busy.value = false;
  }
}
function editSub(item?: Subscription) {
  subDeleting.value = false;
  Object.assign(
    sub,
    item
      ? {
          id: item.id,
          title: item.title,
          time: item.time,
          timezone: item.timezone,
          recurrence: item.recurrence,
          weekday: item.weekday ?? 0,
          session_id: item.session_id,
          enabled: item.enabled,
        }
      : {
          id: "",
          title: "每日安排",
          time: "08:00",
          timezone: zone,
          recurrence: "weekdays",
          weekday: 0,
          session_id: sessionId.value || sessions.value[0]?.session_id || "",
          enabled: true,
        },
  );
  subEditing.value = true;
}
async function saveSub(remove = false) {
  if (busy.value) return;
  busy.value = true;
  error.value = "";
  try {
    const { id, ...body } = sub;
    await requestJson(
      `/api/calendar/subscriptions${id ? "/" + encodeURIComponent(id) : ""}`,
      {
        method: remove ? "DELETE" : id ? "PUT" : "POST",
        body: remove ? undefined : JSON.stringify(body),
      },
    );
    subEditing.value = false;
    await loadSubscriptions();
  } catch (e) {
    error.value = errorMessage(e);
  } finally {
    busy.value = false;
  }
}
const options = computed<CalendarOptions>(() => ({
  plugins: [dayGridPlugin, timeGridPlugin, interactionPlugin, luxonPlugin],
  timeZone: zone,
  locale: zhCn,
  initialView: "dayGridMonth",
  height: "auto",
  headerToolbar: {
    left: "prev,next today",
    center: "title",
    right: "dayGridMonth,timeGridWeek,timeGridDay",
  },
  dayMaxEvents: 3,
  nowIndicator: true,
  events: events.value.map((item) => ({
    id: `${item.id}:${item.occurrence_start || item.start_at}`,
    title: item.title,
    start: item.start_at,
    end: item.end_at,
    allDay: item.all_day,
    extendedProps: { record: item },
  })),
  datesSet(info) {
    range.value = { start: info.startStr, end: info.endStr };
    void loadEvents();
  },
  dateClick(info) {
    edit(undefined, info.dateStr);
  },
  eventClick(info) {
    edit(info.event.extendedProps.record as CalendarEvent);
  },
}));
async function locate() {
  tab.value = "calendar";
  if (calendarTarget.value.date)
    calendar.value?.getApi().gotoDate(calendarTarget.value.date);
  await loadEvents();
  const item =
    events.value.find(
      (e) =>
        e.id === calendarTarget.value.eventId &&
        (!calendarTarget.value.date ||
          e.occurrence_start === calendarTarget.value.date ||
          e.start_at === calendarTarget.value.date),
    ) || events.value.find((e) => e.id === calendarTarget.value.eventId);
  if (item) edit(item);
  else if (calendarTarget.value.eventId)
    error.value = "该事项可能已取消或改期，请在日历中查看。";
}
watch(calendarTarget, () => void locate());
onMounted(() => {
  void loadSubscriptions();
  if (calendarTarget.value.date || calendarTarget.value.eventId) void locate();
});
onBeforeUnmount(() => {
  disposed = true;
  ++revision;
});
</script>
<template>
  <aside
    class="calendar-drawer"
    aria-label="日历侧栏"
    @keydown.esc="calendarOpen = false"
  >
    <header class="calendar-heading">
      <div>
        <p class="eyebrow">留一点空间给生活</p>
        <h2>日历</h2>
      </div>
      <button
        class="icon-button"
        aria-label="关闭日历"
        @click="calendarOpen = false"
      >
        ✕
      </button>
    </header>
    <div class="calendar-tabs">
      <button
        class="button"
        :aria-pressed="tab === 'calendar'"
        @click="tab = 'calendar'"
      >
        日程</button
      ><button
        class="button"
        :aria-pressed="tab === 'subscriptions'"
        @click="
          tab = 'subscriptions';
          loadSubscriptions();
        "
      >
        定时汇报
      </button>
    </div>
    <p v-if="error" class="notice error" role="alert">{{ error }}</p>
    <template v-if="tab === 'calendar'"
      ><div class="calendar-actions">
        <span class="muted small">{{
          loading ? "正在读取日程…" : "点击日期安排一件事"
        }}</span
        ><button class="button primary" @click="edit()">＋ 新建日程</button>
      </div>
      <FullCalendar ref="calendar" :options="options" />
      <form
        v-if="editing"
        class="calendar-editor panel page-stack"
        @submit.prevent="save()"
      >
        <h3>{{ selected ? "编辑日程" : "新的日程" }}</h3>
        <label class="field"
          >标题<input
            v-model="draft.title"
            required
            maxlength="200"
            :disabled="busy" /></label
        ><label class="field"
          >备注<textarea v-model="draft.detail" rows="2" :disabled="busy" />
        </label>
        <div class="calendar-columns">
          <label class="field"
            >开始<input
              :type="draft.all_day ? 'date' : 'datetime-local'"
              v-model="startInput"
              required
              :disabled="busy" /></label
          ><label class="field"
            >结束<input
              :type="draft.all_day ? 'date' : 'datetime-local'"
              v-model="endInput"
              required
              :disabled="busy"
          /></label>
        </div>
        <label
          ><input
            type="checkbox"
            v-model="draft.all_day"
            @change="setAllDay"
            :disabled="busy"
          />
          全天（结束日期不包含当天）</label
        ><label class="field"
          >时区<input v-model="draft.timezone" required :disabled="busy"
        /></label>
        <div class="calendar-columns">
          <label class="field"
            >重复<select v-model="draft.recurrence" :disabled="busy">
              <option value="none">不重复</option>
              <option value="daily">每天</option>
              <option value="weekly">每周</option>
              <option value="weekdays">工作日</option>
            </select></label
          ><label class="field"
            >提醒<select v-model="draft.reminder_minutes" :disabled="busy">
              <option :value="null">不提醒</option>
              <option :value="0">开始时</option>
              <option :value="10">提前 10 分钟</option>
              <option :value="30">提前 30 分钟</option>
              <option :value="60">提前 1 小时</option>
              <option :value="1440">提前 1 天</option>
            </select></label
          >
        </div>
        <label v-if="selected?.recurrence !== 'none' && selected" class="field"
          >应用范围<select v-model="scope" :disabled="busy">
            <option value="single">仅本次</option>
            <option value="series">整个系列</option>
          </select></label
        >
        <div class="calendar-actions">
          <button class="button primary" :disabled="busy">保存</button
          ><button
            type="button"
            class="button"
            :disabled="busy"
            @click="editing = false"
          >
            取消</button
          ><button
            v-if="selected"
            type="button"
            class="button"
            :disabled="busy"
            @click="deleting = true"
          >
            删除
          </button>
        </div>
        <div v-if="deleting" class="notice">
          <p>删除{{ scope === "series" ? "整个系列" : "本次日程" }}？</p>
          <button
            type="button"
            class="button"
            :disabled="busy"
            @click="save(true)"
          >
            确认删除</button
          ><button type="button" class="button" @click="deleting = false">
            保留
          </button>
        </div>
        <div v-if="subDeleting" class="notice">
          <p>删除这项定时汇报？</p>
          <button
            type="button"
            class="button"
            :disabled="busy"
            @click="saveSub(true)"
          >
            确认删除</button
          ><button type="button" class="button" @click="subDeleting = false">
            保留
          </button>
        </div>
      </form></template
    >
    <template v-else
      ><div class="calendar-actions">
        <p class="muted small">在约定时间，把安排送到指定对话。</p>
        <button class="button primary" @click="editSub()">＋ 新建汇报</button>
      </div>
      <p v-if="!subscriptions.length" class="muted">
        还没有订阅。先选择一个接收对话，再约定汇报时间。
      </p>
      <article v-for="item in subscriptions" :key="item.id" class="panel">
        <button class="subscription-link" @click="editSub(item)">
          <strong>{{ item.title }}</strong
          ><span
            >{{ item.time }} · {{ item.enabled ? "已启用" : "已暂停" }}</span
          >
        </button>
        <p v-if="item.last_error" class="notice error">{{ item.last_error }}</p>
      </article>
      <form
        v-if="subEditing"
        class="panel page-stack"
        @submit.prevent="saveSub()"
      >
        <label class="field"
          >汇报名称<input v-model="sub.title" required /></label
        ><label class="field"
          >接收对话<select v-model="sub.session_id" required>
            <option value="" disabled>请选择已有对话</option>
            <option
              v-for="s in sessions"
              :key="s.session_id"
              :value="s.session_id"
            >
              {{ s.title || "新的对话" }}
            </option>
          </select></label
        ><label class="field"
          >时间<input type="time" v-model="sub.time" required /></label
        ><label class="field"
          >时区<input v-model="sub.timezone" required /></label
        ><label class="field"
          >重复<select v-model="sub.recurrence">
            <option value="daily">每天</option>
            <option value="weekdays">工作日</option>
            <option value="weekly">每周</option>
          </select></label
        ><label v-if="sub.recurrence === 'weekly'" class="field"
          >星期<select v-model="sub.weekday">
            <option
              v-for="(day, i) in ['一', '二', '三', '四', '五', '六', '日']"
              :value="i"
              :key="i"
            >
              星期{{ day }}
            </option>
          </select></label
        ><label><input type="checkbox" v-model="sub.enabled" /> 启用订阅</label>
        <div class="calendar-actions">
          <button class="button primary" :disabled="busy">保存</button
          ><button
            type="button"
            class="button"
            :disabled="busy"
            @click="subEditing = false"
          >
            取消</button
          ><button
            v-if="sub.id"
            type="button"
            class="button"
            :disabled="busy"
            @click="subDeleting = true"
          >
            删除订阅
          </button>
        </div>
        <div v-if="subDeleting" class="notice">
          <p>删除这项定时汇报？</p>
          <button
            type="button"
            class="button"
            :disabled="busy"
            @click="saveSub(true)"
          >
            确认删除</button
          ><button type="button" class="button" @click="subDeleting = false">
            保留
          </button>
        </div>
      </form></template
    >
  </aside>
</template>
