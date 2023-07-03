.. SAMPO documentation master file, created by
   sphinx-quickstart on Sun Jul  2 18:31:48 2023.
   You can adapt this file completely to your liking, but it should at least
   contain the root `toctree` directive.

SAMPO
=================================


.. toctree::
   :maxdepth: 1
   :titlesonly:
   :caption: Contents:

   Install
   Features
   Usage

   {% for page in pages %}
   {% if page.top_level_object and page.display %}
   {{ page.include_path }}
   {% endif %}
   {% endfor %}

