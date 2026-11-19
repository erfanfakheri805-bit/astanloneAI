package com.google.ai.edge.litertlm;

/** TEST STAND-IN shaped like the compiled Kotlin `sealed class Backend` (not the real library). */
public abstract class Backend {
    public final String name;

    protected Backend(String name) {
        this.name = name;
    }

    public static final class CPU extends Backend {
        public final Integer threadCount;
        public final Integer numOfThreads;

        public CPU(Integer threadCount, Integer numOfThreads) {
            super("CPU");
            this.threadCount = threadCount;
            this.numOfThreads = numOfThreads;
        }

        public CPU() {                      // Kotlin: a public no-argument constructor when every parameter has a default
            this(null, null);
        }
    }

    public static final class GPU extends Backend {
        public GPU() {
            super("GPU");
        }
    }
}
