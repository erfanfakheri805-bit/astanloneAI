package com.google.ai.edge.litertlm;

import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;

/** TEST STAND-IN: Kotlin `class Contents private constructor` whose factories live in a NON-@JvmStatic companion. */
public final class Contents {
    public static final Companion Companion = new Companion();
    public final List<Content> contents;

    private Contents(List<Content> contents) {
        this.contents = contents;
    }

    @Override
    public String toString() {
        StringBuilder sb = new StringBuilder();
        for (Content c : contents) {
            sb.append(c.toString());
        }
        return sb.toString();
    }

    public static final class Companion {
        private Companion() {
        }

        public Contents of(String text) {
            return of(new Content.Text(text));
        }

        public Contents of(Content... contents) {
            return of(Arrays.asList(contents));
        }

        public Contents of(List<? extends Content> contents) {
            return new Contents(new ArrayList<Content>(contents));
        }
    }
}
