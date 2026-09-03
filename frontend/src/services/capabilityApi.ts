import { HttpResponseError } from "./conversationApi";

export interface ToolCapability {
  name: string;
  description: string;
  inputSchema: Record<string, unknown>;
  permissionRequirements: string[];
  sideEffect: "none" | "reversible" | "irreversible";
  risk: "low" | "medium" | "high";
}

export interface SkillCapability {
  name: string;
  description: string;
  enabled: boolean;
}

export interface Capabilities {
  tools: ToolCapability[];
  skills: SkillCapability[];
}

export interface CapabilityService {
  getCapabilities(signal?: AbortSignal): Promise<Capabilities>;
  setSkillEnabled(
    name: string,
    enabled: boolean,
    signal?: AbortSignal,
  ): Promise<SkillCapability>;
}

interface ApiToolCapability {
  name: string;
  description: string;
  input_schema: Record<string, unknown>;
  permission_requirements: string[];
  side_effect: ToolCapability["sideEffect"];
  risk: ToolCapability["risk"];
}

type FetchRequest = (
  input: RequestInfo | URL,
  init?: RequestInit,
) => Promise<Response>;

function convertTool(tool: ApiToolCapability): ToolCapability {
  return {
    name: tool.name,
    description: tool.description,
    inputSchema: tool.input_schema,
    permissionRequirements: tool.permission_requirements,
    sideEffect: tool.side_effect,
    risk: tool.risk,
  };
}

export class HttpCapabilityService implements CapabilityService {
  constructor(
    private readonly fetchRequest: FetchRequest = globalThis.fetch.bind(
      globalThis,
    ),
    private readonly basePath = "",
  ) {}

  async getCapabilities(signal?: AbortSignal): Promise<Capabilities> {
    const payload = await this.requestJson<{
      tools: ApiToolCapability[];
      skills: SkillCapability[];
    }>("/api/settings/capabilities", { signal });
    return {
      tools: payload.tools.map(convertTool),
      skills: payload.skills,
    };
  }

  async setSkillEnabled(
    name: string,
    enabled: boolean,
    signal?: AbortSignal,
  ): Promise<SkillCapability> {
    const payload = await this.requestJson<{ skill: SkillCapability }>(
      `/api/settings/skills/${encodeURIComponent(name)}/enabled`,
      {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ enabled }),
        signal,
      },
    );
    return payload.skill;
  }

  private async requestJson<T>(path: string, init?: RequestInit): Promise<T> {
    const response = await this.fetchRequest(`${this.basePath}${path}`, init);
    if (!response.ok) {
      throw new HttpResponseError(response.status);
    }
    return (await response.json()) as T;
  }
}
