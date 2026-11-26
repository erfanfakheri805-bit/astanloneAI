package com.erfan.standaloneai;

/**
 * TEST DRIVER (runs on a plain JVM, without Android): the parts of BodyService that need no phone.
 * clean() is the one function that decides what words reach the notification; the three public static methods Python calls must also answer
 * sensibly when there is no Context (a process in which Android is not running them) - false / nothing, never an exception.
 */
public final class BodyServiceMain {
    private static int failures;

    private static void check(String name, boolean ok, String detail) {
        if (ok) {
            System.out.println("PASS " + name);
        } else {
            failures++;
            System.out.println("FAIL " + name + " :: " + detail);
        }
    }

    private static String show(String value) {
        if (value == null) {
            return "null";
        }
        StringBuilder out = new StringBuilder("[");
        for (int i = 0; i < value.length(); i++) {
            char c = value.charAt(i);
            out.append(c < 32 || c > 126 ? String.format("\\u%04x", (int) c) : String.valueOf(c));
        }
        return out.append("] len=").append(value.length()).toString();
    }

    public static void main(String[] args) {
        check("limits_are_the_documented_ones", BodyService.MAX_TITLE == 60 && BodyService.MAX_TEXT == 160, BodyService.MAX_TITLE + "/" + BodyService.MAX_TEXT);

        check("clean_null_is_empty", BodyService.clean(null, 60).equals(""), show(BodyService.clean(null, 60)));
        check("clean_blank_is_empty", BodyService.clean("  \n\t \r\n ", 60).equals(""), show(BodyService.clean("  \n\t \r\n ", 60)));
        String lines = BodyService.clean("  a   b\n\tc \r\n d  ", 60);
        check("clean_collapses_every_run_of_blanks_to_one_space", lines.equals("a b c d"), show(lines));
        check("clean_keeps_a_text_that_fits", BodyService.clean("abcde", 5).equals("abcde"), show(BodyService.clean("abcde", 5)));
        check("clean_cuts_at_the_limit", BodyService.clean("abcdef", 5).equals("abcde"), show(BodyService.clean("abcdef", 5)));
        check("clean_limit_zero_is_empty", BodyService.clean("abc", 0).equals(""), show(BodyService.clean("abc", 0)));

        String pair = "ab😀cd";                                   // a, b, one emoji (two chars), c, d
        check("clean_never_cuts_a_surrogate_pair_in_half", BodyService.clean(pair, 3).equals("ab"), show(BodyService.clean(pair, 3)));
        check("clean_keeps_a_whole_surrogate_pair", BodyService.clean(pair, 4).equals("ab😀"), show(BodyService.clean(pair, 4)));
        check("clean_cuts_right_before_a_pair", BodyService.clean(pair, 2).equals("ab"), show(BodyService.clean(pair, 2)));

        String lone = "ab\uD83D";                                             // malformed (a lone high surrogate at the end) but it fits: kept as it is
        check("clean_keeps_a_text_that_exactly_fits", BodyService.clean(lone, 3).equals(lone), show(BodyService.clean(lone, 3)));

        String persian = "دانلودِ مغزِ خودم";                                 // the words the notification really carries
        check("clean_keeps_persian_words", BodyService.clean(persian, 60).equals(persian), show(BodyService.clean(persian, 60)));
        check("clean_cuts_persian_words_by_chars", BodyService.clean(persian, 6).equals("دانلود"), show(BodyService.clean(persian, 6)));

        StringBuilder long_ = new StringBuilder();
        for (int i = 0; i < 500; i++) {
            long_.append("x ");
        }
        String cut = BodyService.clean(long_.toString(), BodyService.MAX_TEXT);
        check("clean_cuts_a_long_text_to_the_notification_limit", cut.length() == BodyService.MAX_TEXT, "length=" + cut.length());

        boolean threw = false;
        boolean held = true;
        try {
            held = BodyService.hold(null, "title", "text", 5);
        } catch (Throwable t) {
            threw = true;
        }
        check("hold_without_a_context_says_false", !threw && !held, "threw=" + threw + " held=" + held);

        threw = false;
        try {
            BodyService.release(null);
        } catch (Throwable t) {
            threw = true;
        }
        check("release_without_a_context_does_nothing", !threw, "threw");

        threw = false;
        boolean running = true;
        try {
            running = BodyService.isRunning();
        } catch (Throwable t) {
            threw = true;
        }
        check("is_running_is_false_when_nothing_started", !threw && !running, "threw=" + threw + " running=" + running);

        System.out.println("DONE failures=" + failures);
        System.exit(failures == 0 ? 0 : 1);
    }
}
