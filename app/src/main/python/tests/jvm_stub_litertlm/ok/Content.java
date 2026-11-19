package com.google.ai.edge.litertlm;

/** TEST STAND-IN: `sealed class Content` with the one variant the stand-in needs. */
public abstract class Content {
    public static final class Text extends Content {
        public final String text;

        public Text(String text) {
            this.text = text;
        }

        @Override
        public String toString() {
            return text;
        }
    }
}
