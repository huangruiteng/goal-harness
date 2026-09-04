/**
 * Status request fencing for the active-first dashboard.
 *
 * The dashboard loads `goal_activation=active` first, then fills in the stopped
 * archive in the background. Overlapping same-source requests must follow
 * latest-wins: an older response (active or archive) must never overwrite a
 * newer projection. Foreground loads bump `projectionRevision`/`selectionRevision`,
 * but background refreshes intentionally reuse those revisions -- so a separate
 * monotonic `requestGeneration` is assigned to every actually-started request
 * and is what enforces ordering when responses complete out of order.
 */

export type StatusRequestFence = {
  loadedUrl: string | null;
  projectionRevision: number;
  requestedUrl: string | null;
  selectionRevision: number;
  // Monotonic generation assigned to each actually-started status request.
  requestGeneration: number;
};

export type StatusRequest = {
  background: boolean;
  projectionRevision: number;
  selectionRevision: number;
  url: string;
  generation: number;
  registryRevision?: string | null;
};

export function createStatusRequestFence(initialUrl: string | null): StatusRequestFence {
  return {
    loadedUrl: null,
    projectionRevision: 0,
    requestedUrl: initialUrl,
    selectionRevision: 0,
    requestGeneration: 0,
  };
}

export function reserveStatusSourceSelection(fence: StatusRequestFence, url: string) {
  fence.selectionRevision += 1;
  fence.requestedUrl = url;
  return fence.selectionRevision;
}

export function beginStatusRequest(
  fence: StatusRequestFence,
  url: string,
  options: { background: boolean; selectionRevision?: number },
): StatusRequest | null {
  if (options.background) {
    if (fence.requestedUrl !== null || fence.loadedUrl !== url) return null;
    fence.requestGeneration += 1;
    return {
      background: true,
      projectionRevision: fence.projectionRevision,
      selectionRevision: fence.selectionRevision,
      url,
      generation: fence.requestGeneration,
    };
  }
  const selectionRevision = options.selectionRevision ?? fence.selectionRevision + 1;
  if (options.selectionRevision !== undefined && fence.selectionRevision !== selectionRevision) {
    return null;
  }
  fence.selectionRevision = selectionRevision;
  fence.projectionRevision += 1;
  fence.requestedUrl = url;
  fence.requestGeneration += 1;
  return {
    background: false,
    projectionRevision: fence.projectionRevision,
    selectionRevision,
    url,
    generation: fence.requestGeneration,
  };
}

export function statusRequestIsCurrent(fence: StatusRequestFence, request: StatusRequest) {
  return request.generation === fence.requestGeneration
    && fence.projectionRevision === request.projectionRevision
    && fence.selectionRevision === request.selectionRevision;
}

export function statusRequestCanCommit(fence: StatusRequestFence, request: StatusRequest) {
  return statusRequestIsCurrent(fence, request) && (
    !request.background
    || (fence.requestedUrl === null && fence.loadedUrl === request.url)
  );
}

export function resetStatusRequestFence(fence: StatusRequestFence) {
  fence.projectionRevision += 1;
  fence.selectionRevision += 1;
  fence.requestedUrl = null;
  fence.loadedUrl = null;
  fence.requestGeneration += 1;
}
