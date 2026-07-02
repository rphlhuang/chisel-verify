module cocotb_iverilog_dump();
initial begin
    $dumpfile("sim_build/Adder.fst");
    $dumpvars(0, Adder);
end
endmodule
