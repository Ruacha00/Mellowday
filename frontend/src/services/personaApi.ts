import { HttpResponseError } from "./conversationApi";

export interface Persona {
  name: string;
  identity: string;
  character: string;
  speakingStyle: string;
  relationshipFraming: string;
  conversationalBoundaries: string;
  proactiveChatStyle: string;
}

export interface PersonaService {
  getPersona(signal?: AbortSignal): Promise<Persona>;
  updatePersona(persona: Persona, signal?: AbortSignal): Promise<Persona>;
}

interface ApiPersona {
  name: string;
  identity: string;
  character: string;
  speaking_style: string;
  relationship_framing: string;
  conversational_boundaries: string;
  proactive_chat_style: string;
}

type FetchRequest = (
  input: RequestInfo | URL,
  init?: RequestInit,
) => Promise<Response>;

function convertPersona(persona: ApiPersona): Persona {
  return {
    name: persona.name,
    identity: persona.identity,
    character: persona.character,
    speakingStyle: persona.speaking_style,
    relationshipFraming: persona.relationship_framing,
    conversationalBoundaries: persona.conversational_boundaries,
    proactiveChatStyle: persona.proactive_chat_style,
  };
}

function toApiPersona(persona: Persona): ApiPersona {
  return {
    name: persona.name,
    identity: persona.identity,
    character: persona.character,
    speaking_style: persona.speakingStyle,
    relationship_framing: persona.relationshipFraming,
    conversational_boundaries: persona.conversationalBoundaries,
    proactive_chat_style: persona.proactiveChatStyle,
  };
}

export class HttpPersonaService implements PersonaService {
  constructor(
    private readonly fetchRequest: FetchRequest = globalThis.fetch.bind(
      globalThis,
    ),
    private readonly basePath = "",
  ) {}

  async getPersona(signal?: AbortSignal): Promise<Persona> {
    const payload = await this.requestJson<{ persona: ApiPersona }>(
      "/api/settings/persona",
      { signal },
    );
    return convertPersona(payload.persona);
  }

  async updatePersona(
    persona: Persona,
    signal?: AbortSignal,
  ): Promise<Persona> {
    const payload = await this.requestJson<{ persona: ApiPersona }>(
      "/api/settings/persona",
      {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(toApiPersona(persona)),
        signal,
      },
    );
    return convertPersona(payload.persona);
  }

  private async requestJson<T>(path: string, init?: RequestInit): Promise<T> {
    const response = await this.fetchRequest(`${this.basePath}${path}`, init);
    if (!response.ok) {
      throw new HttpResponseError(response.status);
    }
    return (await response.json()) as T;
  }
}
