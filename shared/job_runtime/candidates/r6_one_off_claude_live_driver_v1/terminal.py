from .contracts import validate_terminal
def parse(process_receipt):
    x={"state":process_receipt["terminal_state"],"exact":process_receipt["terminal_state"]=="exact" and process_receipt["exit_code"]==0 and process_receipt["parser_identity"]=="claude_terminal_v1" and process_receipt["output_identity"]=="owner/stdout.raw","parser_identity":process_receipt["parser_identity"],"output_identity":process_receipt["output_identity"]};validate_terminal(x);return x
