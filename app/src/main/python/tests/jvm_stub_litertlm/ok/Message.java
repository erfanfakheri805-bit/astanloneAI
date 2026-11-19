package com.google.ai.edge.litertlm;

import java.util.List;
import java.util.Map;

/** TEST STAND-IN: Kotlin `class Message internal constructor`, factories in the companion (not @JvmStatic). */
public final class Message {
    public static final Companion Companion = new Companion();
    public final String role;
    public final Contents contents;

    Message(String role, Contents contents) {
        this.role = role;
        this.contents = contents;
    }

    @Override
    public String toString() {
        return contents.toString();
    }

    public static final class Companion {
        private Companion() {
        }

        public Message system(String text) {
            return system(Contents.Companion.of(text));
        }

        public Message system(Contents contents) {
            return new Message("system", contents);
        }

        public Message user(String text) {
            return user(Contents.Companion.of(text));
        }

        public Message user(Contents contents) {
            return new Message("user", contents);
        }

        public Message model(String text) {
            return model(Contents.Companion.of(text), null, null);
        }

        public Message model(Contents contents, List<?> toolCalls, Map<String, String> channels) {
            return new Message("assistant", contents);
        }
    }
}
