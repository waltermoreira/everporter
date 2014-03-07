==========
Everporter
==========

Export data from Evernote to a JSON format.

Evernote **does not** export links between notes when using their
export option.  So I wrote a simple script to sync the full account to
a local directory.

Each note, resource, and tag, is exported as a file with the complete
information.

Using
=====

- Install the `Evernote SDK for Python`_.

- Create a developer token in Evernote_. 

- Create a file ``ep.conf`` located in the same directory as the ``ep.py``
  script, containing the developer token.

- Run ``ep.py``

.. _Evernote: https://www.evernote.com/api/DeveloperToken.action
.. _Evernote SDK for Python: https://github.com/evernote/evernote-sdk-python/
