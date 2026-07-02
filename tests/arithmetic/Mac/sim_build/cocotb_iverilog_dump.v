module cocotb_iverilog_dump();
initial begin
    $dumpfile("sim_build/Mac.fst");
    $dumpvars(0, Mac);
end
endmodule
