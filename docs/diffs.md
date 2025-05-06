---
title: "APPG Register Changes"
layout: default
---

# APPG Register Changes

This page lists all available register change reports between consecutive versions of the All-Party Parliamentary Groups Register.

{% assign diff_pages = site.diffs | sort: 'current_register' | reverse %}

## Register Updates

<ul class="diff-list">
{% for diff in diff_pages %}
  <li>
    <a href="{{ site.baseurl }}{{ diff.url }}">
      {{ diff.previous_register }} → {{ diff.current_register }}
    </a>
  </li>
{% endfor %}
</ul>