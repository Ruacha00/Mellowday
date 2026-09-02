export type RequestResult<T> =
  | { status: "current"; value: T }
  | { status: "obsolete" };

export class LatestRequest {
  private generation = 0;
  private controller: AbortController | null = null;

  async run<T>(
    operation: (signal: AbortSignal) => Promise<T>,
  ): Promise<RequestResult<T>> {
    const generation = ++this.generation;
    this.controller?.abort();
    const controller = new AbortController();
    this.controller = controller;

    try {
      const value = await operation(controller.signal);
      if (generation !== this.generation || controller.signal.aborted) {
        return { status: "obsolete" };
      }
      return { status: "current", value };
    } catch (error) {
      if (generation !== this.generation || controller.signal.aborted) {
        return { status: "obsolete" };
      }
      throw error;
    }
  }

  cancel(): void {
    this.generation += 1;
    this.controller?.abort();
    this.controller = null;
  }
}
