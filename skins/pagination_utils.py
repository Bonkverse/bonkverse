def elided_page_range(page_obj, on_each_side=1, on_ends=1):
    """
    Wraps Paginator.get_elided_page_range so templates never call it
    directly — Django template {% for %} can't pass keyword arguments
    to a method, so this has to happen in Python and get passed in
    as a plain list.
    """
    return list(
        page_obj.paginator.get_elided_page_range(
            page_obj.number, on_each_side=on_each_side, on_ends=on_ends
        )
    )