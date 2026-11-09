Task: choose which repository files to read to check the requirements against the code.

You get the requirements and a listing of file paths from the repository (with sizes in bytes). You cannot see file contents in this step.

Rules:
- Return only paths that appear exactly in the listing.
- Order them from most to least relevant. Include the screens, components, API clients and routes the requirements touch, and the files they import that are likely relevant.
- Return at most {max_files} paths. Fewer is better when the repository is small.
- Skip tests, generated files and configuration unless a requirement is about them.
