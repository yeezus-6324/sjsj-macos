(() => {
    const reclaimMode = document.currentScript.dataset.reclaim;
    window.__sjsjSkipReclaim = reclaimMode === "off";
    window.__sjsjEarlierGc = reclaimMode === "early";
    const session = location.pathname.split("/")[2];
    const endpoint = "/report/" + session;
    const state = {
        raf: 0, ticks: 0, logic: 0, frame: 0, submits: 0,
        gcObjects: 0, movieLibraries: 0, collections: 0,
        allocatedBytes: 0, librarySwfBytes: 0, bitmapPixelBytes: 0,
        reclaimHeapBefore: 0, reclaimHeapAfter: 0,
        reclaimBitmapBefore: 0, reclaimBitmapAfter: 0,
        bitmapDisposeCalls: 0, bitmapDisposedMiB: 0,
        bitmapGeneratedBytes: 0, bitmapEmbeddedBytes: 0,
        bitmapSuppliedBytes: 0, bitmapCopyOnWriteBytes: 0,
        playing: false, visible: !document.hidden,
        phase: 0, tickMaxMs: 0, logicMaxMs: 0, renderMaxMs: 0, reclaimMaxMs: 0,
        bitmapPackMaxMs: 0,
        gl: 0, fenceDone: 0, fenceAgeMs: 0, contextLosses: 0,
    };
    let tickStarted = 0;
    let logicStarted = 0;
    let renderStarted = 0;
    let reclaimStarted = 0;
    let bitmapPackStarted = 0;
    let gl;
    let fence;
    let fenceStarted = 0;
    const contexts = new WeakMap();
    const getContext = HTMLCanvasElement.prototype.getContext;
    HTMLCanvasElement.prototype.getContext = function (type, ...args) {
        const context = getContext.call(this, type, ...args);
        if (context && type === "webgl2") contexts.set(this, context);
        return context;
    };

    const send = () => {
        const snapshot = { ...state, visible: !document.hidden };
        fetch(endpoint, { method: "POST", body: "frame-diag " + JSON.stringify(snapshot) }).catch(() => {});
        state.tickMaxMs = 0;
        state.logicMaxMs = 0;
        state.renderMaxMs = 0;
        state.reclaimMaxMs = 0;
        state.bitmapPackMaxMs = 0;
    };

    window.__sjsjFrameDiagnostic = (phase, first, second) => {
        switch (phase) {
            case 0:
                gl = contexts.get(first);
                state.gl = gl ? 1 : 0;
                first.addEventListener("webglcontextlost", () => {
                    state.gl = 2;
                    state.contextLosses++;
                    fence = null;
                    state.fenceAgeMs = 0;
                    send();
                });
                first.addEventListener("webglcontextrestored", () => {
                    state.gl = gl ? 1 : 0;
                    send();
                });
                break;
            case 1:
                tickStarted = performance.now();
                state.phase = 1;
                break;
            case 2:
                reclaimStarted = performance.now();
                state.reclaimHeapBefore = first;
                state.reclaimBitmapBefore = second;
                state.phase = 2;
                break;
            case 3:
                state.logic = first;
                state.frame = second;
                state.logicMaxMs = Math.max(state.logicMaxMs, performance.now() - logicStarted);
                state.phase = 3;
                break;
            case 4:
                renderStarted = performance.now();
                state.phase = 4;
                break;
            case 5:
                state.submits = first;
                state.renderMaxMs = Math.max(state.renderMaxMs, performance.now() - renderStarted);
                state.phase = 5;
                break;
            case 6:
                state.gcObjects = first;
                state.movieLibraries = second;
                break;
            case 7:
                state.collections++;
                state.reclaimHeapAfter = first;
                state.reclaimBitmapAfter = second;
                // A completed cycle and a yielded slice both contribute to the maximum.
            case 18:
                state.reclaimMaxMs = Math.max(state.reclaimMaxMs, performance.now() - reclaimStarted);
                break;
            case 8:
                logicStarted = performance.now();
                state.phase = 8;
                break;
            case 9:
                state.playing = first === 1;
                state.ticks++;
                state.tickMaxMs = Math.max(state.tickMaxMs, performance.now() - tickStarted);
                state.phase = 9;
                break;
            case 10:
                state.allocatedBytes = first;
                state.librarySwfBytes = second;
                break;
            case 11:
                state.bitmapPixelBytes = first;
                break;
            case 12:
                state.bitmapDisposeCalls = first;
                state.bitmapDisposedMiB = second;
                break;
            case 13:
                state.bitmapGeneratedBytes = first;
                state.bitmapEmbeddedBytes = second;
                break;
            case 14:
                state.bitmapSuppliedBytes = first;
                state.bitmapCopyOnWriteBytes = second;
                break;
            case 16:
                bitmapPackStarted = performance.now();
                state.phase = 16;
                break;
            case 17:
                state.bitmapPackMaxMs = Math.max(state.bitmapPackMaxMs, performance.now() - bitmapPackStarted);
                break;
            case 15:
                fetch(endpoint, { method: "POST", body: "bitmap-classes " + first }).catch(() => {});
                break;
        }
    };
    let fencedSubmission = 0;
    function probeGpu() {
        if (!gl || state.gl !== 1 || document.hidden) return;
        const now = performance.now();
        if (fence) {
            // Poll with a zero timeout so the probe never waits on the GPU.
            const result = gl.clientWaitSync(fence, 0, 0);
            if (result === gl.TIMEOUT_EXPIRED) {
                state.fenceAgeMs = now - fenceStarted;
                return;
            }
            gl.deleteSync(fence);
            fence = null;
            state.fenceAgeMs = 0;
            if (result === gl.WAIT_FAILED) {
                state.gl = gl.isContextLost() ? 2 : 3;
                return;
            }
            state.fenceDone++;
        }
        if (state.submits !== fencedSubmission) {
            fencedSubmission = state.submits;
            fence = gl.fenceSync(gl.SYNC_GPU_COMMANDS_COMPLETE, 0);
            if (fence) {
                fenceStarted = now;
                gl.flush();
            }
        }
    }
    function frame() {
        state.raf++;
        requestAnimationFrame(frame);
    }
    requestAnimationFrame(frame);
    setInterval(() => {
        probeGpu();
        send();
    }, 2000);
    document.addEventListener("visibilitychange", send);
    window.addEventListener("error", send);
    window.addEventListener("unhandledrejection", send);
})();
